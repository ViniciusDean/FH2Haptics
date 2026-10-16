"""FH2 Haptics settings window: start/stop the bridge, start it together with the
game, and set every effect from off (0%) to absurd (300%). Changes apply live
and are saved to settings.json."""
import locale
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.environ.get("FH2_SITE"):                     # set by run.bat: HorizonHaptics' venv packages
    import site
    site.addsitedir(os.environ["FH2_SITE"])

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
                               QScrollArea, QSlider, QTabWidget, QVBoxLayout, QWidget)

from fh2_haptics import Bridge                      # first: it puts HorizonHaptics on sys.path
from fh2_effects import LEVEL_MAX, LEVELS, load_settings, save_settings
from fh2_snapshot import OUT_DIR

TEXT = {
    "en": {
        "title": "FH2 Haptics",
        "run": "Run", "start": "Start", "stop": "Stop",
        "start_game": "Start game + FH2 Haptics", "browse": "Browse...",
        "game_exe": "Game (azimuth.exe):", "pick_exe": "Select azimuth.exe",
        "no_exe": "Pick azimuth.exe first.",
        "triggers": "Triggers", "body": "Body haptics", "debug": "Debug",
        "lightbar": "RPM light on", "haptics_on": "Body haptics on (restarts the bridge)",
        "rpm_tab": "RPM light", "rpm_start": "Comes on at", "rpm_flash": "Flashes (shift) at",
        "rpm_hz": "Flash speed", "rpm_bright": "Brightness", "rpm_low": "Color: low",
        "rpm_mid": "Color: middle", "rpm_high": "Color: high", "rpm_flashc": "Color: flashing",
        "of_rpm": "of max RPM", "solid": "solid",
        "body_on": "Body haptics: on", "body_err": "Body haptics: controller audio not available, retrying... (see Debug)",
        "beep": "Beep on the PC for every object hit", "lock": "Lock both triggers for 1 s on every object hit",
        "snap_hint": "Press the DualSense mute button (or F8) while driving to save a snapshot.",
        "open_snaps": "Open snapshots folder", "reset": "Reset all to 100%",
        "language": "Language:",
        "st_stopped": "Stopped", "st_waiting": "Waiting for the game...", "st_paused": "Game paused / in menu",
        "st_running": "{kmh:.0f} km/h  ·  gear {gear}  ·  {effect}",
        "off": "Off", "weak": "Weak", "normal": "Normal", "strong": "Strong", "absurd": "Absurd",
        "levels": {
            "brake_pedal": "Brake pedal (L2 resistance)", "abs_trigger": "ABS pulse (L2)",
            "lock_trigger": "Wheel lock-up (L2)", "throttle": "Throttle resistance (R2)",
            "spin_trigger": "Wheelspin / sliding (R2)", "shift_trigger": "Gear change kick (R2)",
            "object_trigger": "Object hits (both triggers)", "crash_trigger": "Crashes (both triggers)",
            "volume": "Master volume", "traction": "Traction loss", "understeer": "Front tires sliding",
            "surface": "Surface texture (dirt, grass)", "detail": "Small road details",
            "object_hit": "Object hits (bollards, signs)", "crash": "Crashes (walls, cars)",
            "landing": "Jump landings", "abs_body": "ABS pulse", "shift_body": "Gear changes",
            "engine": "Engine growl",
        },
    },
    "pt": {
        "title": "FH2 Haptics",
        "run": "Execução", "start": "Iniciar", "stop": "Parar",
        "start_game": "Iniciar jogo + FH2 Haptics", "browse": "Procurar...",
        "game_exe": "Jogo (azimuth.exe):", "pick_exe": "Selecione o azimuth.exe",
        "no_exe": "Escolha o azimuth.exe primeiro.",
        "triggers": "Gatilhos", "body": "Vibração do corpo", "debug": "Debug",
        "lightbar": "Luz do RPM ligada", "haptics_on": "Vibração do corpo ligada (reinicia a ponte)",
        "rpm_tab": "Luz do RPM", "rpm_start": "Acende a partir de", "rpm_flash": "Pisca (trocar marcha) a partir de",
        "rpm_hz": "Velocidade do pisca", "rpm_bright": "Brilho", "rpm_low": "Cor: início",
        "rpm_mid": "Cor: meio", "rpm_high": "Cor: fim", "rpm_flashc": "Cor: piscando",
        "of_rpm": "do RPM máximo", "solid": "fixa",
        "body_on": "Vibração do corpo: ativa", "body_err": "Vibração do corpo: áudio do controle indisponível, tentando de novo... (veja Debug)",
        "beep": "Apitar no PC a cada objeto batido", "lock": "Travar os gatilhos por 1 s a cada objeto batido",
        "snap_hint": "Aperte o botão de mudo do DualSense (ou F8) dirigindo para salvar um snapshot.",
        "open_snaps": "Abrir pasta de snapshots", "reset": "Voltar tudo para 100%",
        "language": "Idioma:",
        "st_stopped": "Parado", "st_waiting": "Aguardando o jogo...", "st_paused": "Jogo pausado / no menu",
        "st_running": "{kmh:.0f} km/h  ·  marcha {gear}  ·  {effect}",
        "off": "Desligado", "weak": "Fraco", "normal": "Normal", "strong": "Forte", "absurd": "Absurdo",
        "levels": {
            "brake_pedal": "Pedal de freio (resistência no L2)", "abs_trigger": "Pulso do ABS (L2)",
            "lock_trigger": "Roda travando (L2)", "throttle": "Resistência do acelerador (R2)",
            "spin_trigger": "Patinada / traseira saindo (R2)", "shift_trigger": "Tranco da troca de marcha (R2)",
            "object_trigger": "Batidinhas em objetos (gatilhos)", "crash_trigger": "Batidas fortes (gatilhos)",
            "volume": "Volume geral", "traction": "Perda de tração", "understeer": "Saindo de frente",
            "surface": "Textura do piso (terra, grama)", "detail": "Detalhes do asfalto",
            "object_hit": "Batidinhas (balizadores, placas)", "crash": "Batidas fortes (parede, carro)",
            "landing": "Pouso de pulo", "abs_body": "Pulso do ABS", "shift_body": "Troca de marcha",
            "engine": "Ronco do motor",
        },
    },
}


def system_language():
    lang = (locale.getdefaultlocale()[0] or "").lower()
    return "pt" if lang.startswith("pt") else "en"


class LevelSlider(QWidget):
    """0..300 % slider with a word next to it."""

    def __init__(self, value, words, on_change):
        super().__init__()
        self.words = words
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, int(LEVEL_MAX * 100))
        self.slider.setSingleStep(5)
        self.slider.setPageStep(25)
        self.slider.setValue(int(round(value * 100)))
        self.label = QLabel()
        self.label.setMinimumWidth(130)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self.slider.valueChanged.connect(lambda v: (self._update(), on_change(v / 100.0)))
        self._update()

    def _update(self):
        v = self.slider.value()
        w = self.words
        word = (w["off"] if v == 0 else w["weak"] if v < 70 else w["normal"] if v <= 130
                else w["strong"] if v <= 220 else w["absurd"])
        self.label.setText(f"{v}%  ·  {word}")


class ValueSlider(QWidget):
    """Slider over [lo, hi] (floats) with a formatted label."""

    def __init__(self, value, lo, hi, step, fmt, on_change):
        super().__init__()
        self.lo, self.step, self.fmt = lo, step, fmt
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, int(round((hi - lo) / step)))
        self.slider.setValue(int(round((value - lo) / step)))
        self.label = QLabel()
        self.label.setMinimumWidth(130)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self.slider.valueChanged.connect(lambda _: (self._update(), on_change(self.value())))
        self._update()

    def value(self):
        return round(self.lo + self.slider.value() * self.step, 4)

    def _update(self):
        self.label.setText(self.fmt(self.value()))


class ColorButton(QPushButton):
    def __init__(self, rgb, on_change):
        super().__init__()
        self.rgb, self.on_change = list(rgb), on_change
        self.setFixedWidth(120)
        self.clicked.connect(self._pick)
        self._paint()

    def _paint(self):
        r, g, b = self.rgb
        fg = "black" if r * 0.3 + g * 0.6 + b * 0.1 > 140 else "white"
        self.setText("#%02X%02X%02X" % (r, g, b))
        self.setStyleSheet(f"background: rgb({r},{g},{b}); color: {fg};")

    def _pick(self):
        c = QColorDialog.getColor(QColor(*self.rgb), self)
        if c.isValid():
            self.rgb = [c.red(), c.green(), c.blue()]
            self._paint()
            self.on_change(self.rgb)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.raw = load_settings()
        self.lang = self.raw.get("language") or system_language()
        self.t = TEXT[self.lang]
        self.bridge = None
        self.game_proc = None
        self._save_timer = QTimer(self, singleShot=True, interval=300, timeout=self._save)
        self.setWindowTitle(self.t["title"])
        self.resize(640, 720)
        self._build()
        self._status_timer = QTimer(self, interval=200, timeout=self._refresh_status)
        self._status_timer.start()
        if self.raw.get("autostart", True):
            QTimer.singleShot(300, self.start)

    # -- layout ------------------------------------------------------------------
    def _build(self):
        t = self.t
        root = QWidget()
        lay = QVBoxLayout(root)

        run = QGroupBox(t["run"])
        rl = QVBoxLayout(run)
        self.status = QLabel(t["st_stopped"])
        self.status.setStyleSheet("font-size: 15px; font-weight: bold;")
        rl.addWidget(self.status)
        self.sub = QLabel()
        self.sub.setStyleSheet("color: gray;")
        rl.addWidget(self.sub)
        row = QHBoxLayout()
        self.btn_start = QPushButton(t["start"])
        self.btn_start.clicked.connect(self.toggle)
        self.btn_game = QPushButton(t["start_game"])
        self.btn_game.clicked.connect(self.start_with_game)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_game)
        rl.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel(t["game_exe"]))
        self.exe = QLineEdit(self.raw.get("game_exe", ""))
        self.exe.editingFinished.connect(self._exe_changed)
        browse = QPushButton(t["browse"])
        browse.clicked.connect(self.pick_exe)
        row.addWidget(self.exe, 1)
        row.addWidget(browse)
        rl.addLayout(row)
        lay.addWidget(run)

        tabs = QTabWidget()
        tabs.addTab(self._levels_tab("triggers", []), t["triggers"])
        tabs.addTab(self._levels_tab("body", [self._check(("haptics", "enabled"), t["haptics_on"],
                                                          restart=True)]), t["body"])
        tabs.addTab(self._rpm_tab(), t["rpm_tab"])
        tabs.addTab(self._debug_tab(), t["debug"])
        lay.addWidget(tabs, 1)

        bottom = QHBoxLayout()
        reset = QPushButton(t["reset"])
        reset.clicked.connect(self.reset_levels)
        bottom.addWidget(reset)
        bottom.addStretch(1)
        bottom.addWidget(QLabel(t["language"]))
        self.lang_box = QComboBox()
        self.lang_box.addItems(["Português", "English"])
        self.lang_box.setCurrentIndex(0 if self.lang == "pt" else 1)
        self.lang_box.currentIndexChanged.connect(self._lang_changed)
        bottom.addWidget(self.lang_box)
        lay.addLayout(bottom)
        self.setCentralWidget(root)

    def _levels_tab(self, group, extras):
        words = self.t
        inner = QWidget()
        form = QFormLayout(inner)
        for w in extras:
            form.addRow(w)
        self.sliders = getattr(self, "sliders", {})
        for name, (grp, _) in LEVELS.items():
            if grp != group:
                continue
            value = self.raw.setdefault("levels", {}).get(name, 1.0)
            s = LevelSlider(value, words, lambda v, n=name: self._level_changed(n, v))
            self.sliders[name] = s
            form.addRow(self.t["levels"][name], s)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        return scroll

    def _rpm_tab(self):
        t, L = self.t, self.raw["rpm_light"]
        w = QWidget()
        form = QFormLayout(w)
        form.addRow(self._check("lightbar", t["lightbar"]))

        def setter(key):
            def f(v):
                L[key] = v
                self._changed()
            return f

        pct = lambda v: f"{v * 100:.0f}% {t['of_rpm']}"
        form.addRow(t["rpm_start"], ValueSlider(L["start"], 0.1, 0.99, 0.01, pct, setter("start")))
        form.addRow(t["rpm_flash"], ValueSlider(L["flash"], 0.5, 1.0, 0.01, pct, setter("flash")))
        form.addRow(t["rpm_hz"], ValueSlider(L["flash_hz"], 0.0, 20.0, 0.5,
                                             lambda v: f"{v:.1f} Hz" if v else t["solid"], setter("flash_hz")))
        form.addRow(t["rpm_bright"], ValueSlider(L["brightness"], 0.0, 1.0, 0.05,
                                                 lambda v: f"{v * 100:.0f}%", setter("brightness")))

        def color_setter(i):
            def f(rgb):
                L["colors"][i] = rgb
                self._changed()
            return f

        for i, key in enumerate(("rpm_low", "rpm_mid", "rpm_high")):
            form.addRow(t[key], ColorButton(L["colors"][i], color_setter(i)))
        form.addRow(t["rpm_flashc"], ColorButton(L["flash_color"], setter("flash_color")))
        return w

    def _debug_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._check("debug_beep_on_hit", self.t["beep"]))
        lay.addWidget(self._check("debug_lock_on_hit", self.t["lock"]))
        hint = QLabel(self.t["snap_hint"])
        hint.setWordWrap(True)
        lay.addWidget(hint)
        btn = QPushButton(self.t["open_snaps"])
        btn.clicked.connect(lambda: (os.makedirs(OUT_DIR, exist_ok=True), os.startfile(OUT_DIR)))
        lay.addWidget(btn)
        self.log = QLabel()
        self.log.setWordWrap(True)
        self.log.setStyleSheet("color: gray;")
        lay.addWidget(self.log)
        lay.addStretch(1)
        return w

    def _check(self, key, text, restart=False):
        node, leaf = (self.raw[key[0]], key[1]) if isinstance(key, tuple) else (self.raw, key)
        box = QCheckBox(text)
        box.setChecked(bool(node.get(leaf, True)))

        def changed(on):
            node[leaf] = bool(on)
            self._changed()
            if restart and self.bridge and self.bridge.running:
                self.stop()
                self.start()
        box.toggled.connect(changed)
        return box

    # -- settings ------------------------------------------------------------------
    def _level_changed(self, name, value):
        self.raw.setdefault("levels", {})[name] = round(value, 2)
        self._changed()

    def _changed(self):
        if self.bridge:
            self.bridge.apply(self.raw)
        self._save_timer.start()

    def _save(self):
        try:
            save_settings(self.raw)
        except OSError:
            pass

    def reset_levels(self):
        for s in self.sliders.values():
            s.slider.setValue(100)

    def _lang_changed(self, idx):
        self.raw["language"] = "pt" if idx == 0 else "en"
        self._save()
        running = self.bridge and self.bridge.running
        self.lang, self.t = self.raw["language"], TEXT[self.raw["language"]]
        self.sliders = {}
        self.setWindowTitle(self.t["title"])
        self._build()
        self.btn_start.setText(self.t["stop"] if running else self.t["start"])

    def _exe_changed(self):
        self.raw["game_exe"] = self.exe.text().strip()
        self._save()

    def pick_exe(self):
        start = os.path.dirname(self.exe.text()) if self.exe.text() else ""
        path, _ = QFileDialog.getOpenFileName(self, self.t["pick_exe"], start, "azimuth.exe (azimuth.exe);;*.exe (*.exe)")
        if path:
            self.exe.setText(os.path.normpath(path))
            self._exe_changed()

    # -- running -------------------------------------------------------------------
    def start(self):
        if self.bridge and self.bridge.running:
            return
        self.bridge = Bridge(self.raw)
        self.bridge.start()
        self.btn_start.setText(self.t["stop"])

    def stop(self):
        if self.bridge:
            self.bridge.stop()
        self.btn_start.setText(self.t["start"])

    def toggle(self):
        if self.bridge and self.bridge.running:
            self.stop()
        else:
            self.start()

    def start_with_game(self):
        exe = self.exe.text().strip()
        if not exe or not os.path.isfile(exe):
            QMessageBox.warning(self, self.t["title"], self.t["no_exe"])
            self.pick_exe()
            exe = self.exe.text().strip()
            if not exe or not os.path.isfile(exe):
                return
        self.game_proc = subprocess.Popen([exe], cwd=os.path.dirname(exe))
        self.start()

    def _refresh_status(self):
        b = self.bridge
        st = b.status if b else {"state": "stopped"}
        if b and not b.running and st.get("state") != "stopped":
            st = {"state": "stopped"}
        state = st.get("state", "stopped")
        if state == "running":
            text = self.t["st_running"].format(kmh=st.get("kmh", 0), gear=st.get("gear", 0),
                                               effect=st.get("effect", "") or "-")
        else:
            text = self.t["st_" + state]
        self.status.setText(text)
        if b and b.messages:
            self.log.setText("\n".join(b.messages[-6:]))
        if b and b.running and b.status.get("state") != "stopped":
            if b.haptics:
                self.sub.setText(self.t["body_on"])
            elif b.cfg["haptics"]["enabled"]:
                self.sub.setText(self.t["body_err"])
            else:
                self.sub.setText("")
        else:
            self.sub.setText("")
        if not (b and b.running) and self.btn_start.text() != self.t["start"]:
            self.btn_start.setText(self.t["start"])

    def closeEvent(self, ev):
        self._save()
        self.stop()
        super().closeEvent(ev)


def main():
    app = QApplication(sys.argv)
    w = Window()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
