"""简洁面板：每台设备一张卡片，大号百分比 + 进度条 + 来源。"""
from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import monitor as mon
import protocols as P

BG = "#f5f6f8"
CARD = "#ffffff"
TXT = "#1f2430"
SUB = "#7b8494"
GREEN = "#2fbf71"
AMBER = "#f0a53a"
RED = "#e05a5a"
GREY = "#a7b0c0"

SCALE = 1.0


def px(n: float) -> int:
    return int(round(n * SCALE))


def level_color(level: int | None) -> str:
    if level is None:
        return GREY
    if level >= 60:
        return GREEN
    if level >= 30:
        return AMBER
    return RED


class Card(tk.Frame):
    def __init__(self, master, reading: P.Reading):
        super().__init__(master, bg=CARD, highlightbackground="#e6e9ef",
                         highlightthickness=1, bd=0)
        self.reading = reading
        self.grid_columnconfigure(1, weight=1)

        self.name = tk.Label(self, text=reading.name, bg=CARD, fg=TXT,
                             font=("Microsoft YaHei UI", 12, "bold"), anchor="w")
        self.name.grid(row=0, column=0, columnspan=2, sticky="we", padx=px(16), pady=(px(14), 0))

        self.pct = tk.Label(self, text="—", bg=CARD, fg=GREY,
                            font=("Segoe UI", 30, "bold"), anchor="w")
        self.pct.grid(row=1, column=0, sticky="w", padx=px(16), pady=(px(2), 0))

        self.right = tk.Frame(self, bg=CARD)
        self.right.grid(row=1, column=1, sticky="e", padx=px(16))
        self.chg = tk.Label(self.right, text="", bg=CARD, fg="#2f8f4e",
                            font=("Microsoft YaHei UI", 9, "bold"), anchor="e")
        self.chg.pack(side="top", anchor="e")
        self.tag = tk.Label(self.right, text=reading.transport, bg=CARD, fg=SUB,
                            font=("Microsoft YaHei UI", 9), anchor="e")
        self.tag.pack(side="top", anchor="e")

        self.bar = tk.Canvas(self, height=px(10), bg=CARD, highlightthickness=0, bd=0)
        self.bar.grid(row=2, column=0, columnspan=2, sticky="we", padx=px(16), pady=(px(6), 0))
        self._bar_bg = self.bar.create_rectangle(0, 0, 0, px(10), fill="#eceff4", width=0)
        self._bar_fg = self.bar.create_rectangle(0, 0, 0, px(10), fill=GREY, width=0)

        self.detail = tk.Label(self, text="", bg=CARD, fg=SUB,
                               font=("Microsoft YaHei UI", 9), anchor="w",
                               wraplength=px(420), justify="left")
        self.detail.grid(row=3, column=0, columnspan=2, sticky="we", padx=px(16), pady=(px(8), px(14)))

        self.bar.bind("<Configure>", lambda e: self._draw_bar())

    def update_reading(self, r: P.Reading) -> None:
        self.reading = r
        has = r.level is not None
        self.pct.config(text=f"{r.level}%" if has else "—", fg=level_color(r.level),
                        font=("Segoe UI", 30, "bold"))
        status = "" if r.status == "ok" else f" · {r.status_text}"
        if r.status == "cached" and r.age_text():
            status += f" {r.age_text()}"
        self.tag.config(text=f"{r.transport}{status}", fg=SUB if r.status == "ok" else AMBER)
        if r.charging:
            self.chg.config(text="⚡ 已充满" if (r.level or 0) >= 100 else "⚡ 充电中")
        else:
            self.chg.config(text="")
        when = r.age_text()
        detail = r.detail
        if has and when and r.status in ("idle", "error", "offline"):
            detail = f"{detail}（{when}）" if detail else when
        self.detail.config(text=detail)
        self._draw_bar()

    def _draw_bar(self) -> None:
        w = self.bar.winfo_width() or 1
        h = px(10)
        self.bar.coords(self._bar_bg, 0, 0, w, h)
        lvl = self.reading.level or 0
        self.bar.coords(self._bar_fg, 0, 0, max(0, int(w * lvl / 100)), h)
        self.bar.itemconfig(self._bar_fg, fill=level_color(self.reading.level))


class App(tk.Tk):
    def __init__(self, ref: mon.Monitor, start_hidden: bool = False):
        super().__init__()
        global SCALE
        try:
            dpi = float(self.winfo_fpixels("1i"))
        except Exception:
            dpi = 96.0
        SCALE = float(os.environ.get("DSH_UI_SCALE") or max(1.0, dpi / 96.0))
        try:
            self.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass
        self.monitor = ref
        self.tray = None
        self.commands: queue.Queue[str] = queue.Queue()
        self.title("设备电量")
        self.geometry(f"{px(480)}x{px(620)}")
        self.minsize(px(420), px(480))
        self.configure(bg=BG)
        self.cards: dict[str, Card] = {}
        self._order: list[str] = []

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=px(18), pady=(px(16), px(6)))
        tk.Label(header, text="设备电量", bg=BG, fg=TXT,
                 font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        self.settings_btn = tk.Button(header, text="设置", command=self.open_settings,
                                      relief="flat", bg=BG, fg=SUB, bd=0,
                                      activebackground="#e9edf3",
                                      font=("Microsoft YaHei UI", 9), padx=8, pady=4)
        self.settings_btn.pack(side="right")
        self.refresh_btn = tk.Button(header, text="立即刷新", command=self.refresh,
                                     relief="flat", bg="#e9edf3", fg=TXT, bd=0,
                                     activebackground="#dde3ec",
                                     font=("Microsoft YaHei UI", 9), padx=12, pady=4)
        self.refresh_btn.pack(side="right", padx=(0, 6))

        self.hint = tk.Label(self, text="关掉这个窗口会缩到状态栏，随时点托盘图标再打开。",
                             bg=BG, fg=SUB, font=("Microsoft YaHei UI", 9), anchor="w")
        self.hint.pack(fill="x", padx=px(18), pady=(0, px(8)))

        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True, padx=px(14), pady=(0, px(8)))

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="x", padx=px(18), pady=(0, px(12)))
        self.elevate_btn = tk.Button(bottom, text="以管理员重启", command=self.relaunch_admin,
                                     relief="flat", bg="#f0d9d3", fg="#8a3a24", bd=0,
                                     font=("Microsoft YaHei UI", 8), padx=px(8), pady=px(2),
                                     activebackground="#e7c8c0")
        self.footer = tk.Label(bottom, text="", bg=BG, fg=SUB,
                               font=("Microsoft YaHei UI", 8), anchor="w", justify="left",
                               wraplength=px(320))
        self.footer.pack(side="left", fill="x", expand=True)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(300, self.tick)
        self.after(400, self.poll_commands)
        if start_hidden:
            self.withdraw()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.monitor.refresh_now()
        self.hint.config(text="已请求刷新：蓝牙重新枚举、接收器已戳一下；键盘需按键唤醒。")
        self.after(3000, lambda: self.hint.config(
            text="关掉这个窗口会缩到状态栏，随时点托盘图标再打开。"))

    def show_panel(self) -> None:
        self.deiconify()
        self.lift()
        try:
            self.focus_force()
        except Exception:
            pass

    def on_close(self) -> None:
        """点 × 收进托盘；如果托盘没建起来（比如权限问题），就直接退出，免得窗口消失后没法再打开。"""
        if getattr(self.tray, "ok", False):
            self.withdraw()
        else:
            self.quit_app()

    def relaunch_admin(self) -> None:
        """托盘被 UIPI 拦住时（资源管理器是高权限），用管理员身份重启一次。"""
        import ctypes
        import sys
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, ""
        else:
            exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if not os.path.exists(exe):
                exe = sys.executable
            params = '"' + os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py") + '"'
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        except Exception:
            return
        self.quit_app()

    def quit_app(self) -> None:
        self.monitor.stop()
        if self.tray:
            self.tray.stop()
        self.destroy()

    def poll_commands(self) -> None:
        while True:
            try:
                cmd = self.commands.get_nowait()
            except queue.Empty:
                break
            if cmd == "open":
                self.show_panel()
            elif cmd == "refresh":
                self.refresh()
            elif cmd == "quit":
                self.quit_app()
                return
        self.after(300, self.poll_commands)

    def tick(self) -> None:
        snap = self.monitor.snapshot()
        self._sync(snap.readings)
        self._update_footer(snap)
        self.after(1000, self.tick)

    def _update_footer(self, snap) -> None:
        parts = [f"最后检查 {time.strftime('%H:%M:%S', time.localtime(snap.ts))}"]
        err = getattr(self.tray, "last_error", "") if self.tray else ""
        if err:
            parts.append(f"托盘未生效：{err}")
            self.footer.config(fg="#c0563a")
            if "可通信=False" in err:
                if not self.elevate_btn.winfo_ismapped():
                    self.elevate_btn.pack(side="right", padx=(px(8), 0), before=self.footer)
        else:
            parts.append("托盘已就绪")
            self.footer.config(fg=SUB)
            if self.elevate_btn.winfo_ismapped():
                self.elevate_btn.pack_forget()
        self.footer.config(text="  ·  ".join(parts))

    # ------------------------------------------------------------------
    def open_settings(self) -> None:
        import settings as cfg

        win = tk.Toplevel(self)
        win.title("设置")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        win.geometry(f"{px(420)}x{px(400)}+{self.winfo_rootx() + 70}+{self.winfo_rooty() + 80}")

        cur = cfg.load()
        mouse_var = tk.StringVar(value=str(int(cur.get("mouse_interval", 5))))
        bt_var = tk.BooleanVar(value=bool(cur.get("show_bluetooth", True)))
        auto_var = tk.BooleanVar(value=cfg.autostart_enabled())
        hidden_var = tk.BooleanVar(value=bool(cur.get("start_hidden", False)))

        disabled0 = set(cur.get("disabled_devices") or [])
        devs = self.monitor.known_devices()
        for key in disabled0:                      # 关掉且当前不在线的也列出来
            devs.setdefault(key, key)

        f = ("Microsoft YaHei UI", 10)
        small = ("Microsoft YaHei UI", 9, "bold")

        h = 420 + 30 * max(0, len(devs) - 2)
        win.geometry(f"{px(420)}x{px(min(h, 640))}+{self.winfo_rootx() + 70}+{self.winfo_rooty() + 80}")

        # 按钮先占住底部，内容再多也不会把它挤出去
        btns = tk.Frame(win, bg=BG)
        btns.pack(side="bottom", fill="x", padx=px(22), pady=(0, px(14)))

        box = tk.Frame(win, bg=BG)
        box.pack(fill="both", expand=True, padx=px(22), pady=(px(16), 0))

        row = tk.Frame(box, bg=BG)
        row.pack(fill="x", pady=(0, 6))
        tk.Label(row, text="鼠标刷新间隔", bg=BG, fg=TXT, font=f).pack(side="left")
        for sec in ("2", "5", "10", "30"):
            tk.Radiobutton(row, text=sec, variable=mouse_var, value=sec, bg=BG,
                           fg=TXT, activebackground=BG, font=f, bd=0,
                           highlightthickness=0, selectcolor="#ffffff",
                           padx=0).pack(side="left", padx=(8, 0))

        def chk(text, var):
            tk.Checkbutton(box, text=text, variable=var, bg=BG, fg=TXT,
                           activebackground=BG, activeforeground=TXT, font=f,
                           anchor="w", bd=0, highlightthickness=0,
                           selectcolor="#ffffff", padx=0).pack(fill="x", pady=3)

        def section(text):
            tk.Frame(box, bg="#e3e7ee", height=1).pack(fill="x", pady=(8, 4))
            tk.Label(box, text=text, bg=BG, fg=SUB, font=small,
                     anchor="w").pack(fill="x", pady=(0, 2))

        chk("显示蓝牙设备", bt_var)

        section("设备列表（取消勾选就不显示，也不占托盘）")
        dev_vars: dict[str, tk.BooleanVar] = {}
        if devs:
            for key, name in devs.items():
                var = tk.BooleanVar(value=key not in disabled0)
                dev_vars[key] = var
                chk(name, var)
        else:
            tk.Label(box, text="还没发现设备。接上接收器/唤醒键盘后再打开这里。",
                     bg=BG, fg=SUB, anchor="w", font=("Microsoft YaHei UI", 8)).pack(fill="x")

        section("启动")
        chk("开机自启（启动文件夹快捷方式）", auto_var)
        chk("启动时只留托盘，不弹面板", hidden_var)

        tip = tk.Label(box, text="", bg=BG, fg=SUB, anchor="w", font=("Microsoft YaHei UI", 8))
        tip.pack(fill="x", pady=(6, 0))

        def do_save():
            data = dict(cur)
            data["mouse_interval"] = float(mouse_var.get() or 5)
            data["show_bluetooth"] = bool(bt_var.get())
            data["start_hidden"] = bool(hidden_var.get())
            new_dis = set(disabled0)
            for key, var in dev_vars.items():
                if var.get():
                    new_dis.discard(key)
                else:
                    new_dis.add(key)
            data["disabled_devices"] = sorted(new_dis)
            cfg.save(data)
            self.monitor.mouse_interval = data["mouse_interval"]
            self.monitor.show_bt = data["show_bluetooth"]
            self.monitor.disabled = set(new_dis)
            ok, msg = True, ""
            if bool(auto_var.get()) != cfg.autostart_enabled():
                ok, msg = cfg.set_autostart(bool(auto_var.get()))
            tip.config(text="已保存" if ok else f"开机自启失败：{msg}",
                       fg=SUB if ok else "#c0563a")
            self.after(900, win.destroy)

        tk.Button(btns, text="保存", command=do_save, relief="flat", bg="#2f6feb",
                  fg="white", bd=0, font=f, padx=22, pady=4,
                  activebackground="#2559c4").pack(side="right")
        tk.Button(btns, text="取消", command=win.destroy, relief="flat", bg="#e9edf3",
                  fg=TXT, bd=0, font=f, padx=16, pady=4,
                  activebackground="#dde3ec").pack(side="right", padx=(0, 8))

    def _sync(self, readings: list[P.Reading]) -> None:
        live = {r.key: r for r in readings}
        for key in list(self.cards):
            if key not in live:
                self.cards.pop(key).destroy()
        for key in live:
            if key not in self.cards:
                self.cards[key] = Card(self.body, live[key])
        order = [r.key for r in readings]
        if order != self._order:
            for key in order:
                self.cards[key].pack_forget()
            for key in order:
                self.cards[key].pack(fill="x", pady=px(6))
            self._order = order
        for r in readings:
            self.cards[r.key].update_reading(r)


def run(start_hidden: bool = False) -> None:
    import settings as cfg
    import tray as tray_mod

    st = cfg.load()

    # 自启开着但快捷方式指向旧位置（程序被挪过目录）时，后台自动修好
    def _fix_autostart() -> None:
        try:
            ok, msg = cfg.refresh_autostart()
            if msg not in ("ok", "未开启"):
                print(f"[autostart] {msg}", flush=True)
        except Exception:
            pass

    threading.Thread(target=_fix_autostart, daemon=True).start()

    m = mon.Monitor(mouse_interval=float(st.get("mouse_interval", 5.0)),
                    show_bt=bool(st.get("show_bluetooth", True)),
                    disabled=set(st.get("disabled_devices") or [])).start()
    app = App(m, start_hidden=start_hidden or bool(st.get("start_hidden", False)))
    t = tray_mod.Tray(snapshot=m.snapshot, on_command=app.commands.put)
    app.tray = t
    t.start()
    try:
        app.mainloop()
    finally:
        m.stop()
        t.stop()


if __name__ == "__main__":
    run()
