"""Музыка и эффекты для ролика — одной пьесой, синтезом на numpy.

120 BPM (доля 0.5 с), 22 с. Ля минор → до мажор: Am – F – C – G.
Эффекты сделаны из тех же нот и лежат под музыкой.
"""
import wave

import numpy as np

SR = 48000
DUR = 22.0
BEAT = 0.5
N = int(SR * DUR)
rng = np.random.default_rng(7)


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def env(n, a, d, s, r, sus_len):
    """ADSR в сэмплах."""
    a, d, r = int(a * SR), int(d * SR), int(r * SR)
    sus_len = max(0, int(sus_len * SR) - a - d)
    e = np.concatenate([
        np.linspace(0, 1, max(a, 1)), np.linspace(1, s, max(d, 1)),
        np.full(sus_len, s), np.linspace(s, 0, max(r, 1))])
    return e[:n] if len(e) >= n else np.pad(e, (0, n - len(e)))


def lowpass(x, cutoff):
    # однополюсный фильтр — мягко срезает верх
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def add(buf, sig, t):
    i = int(t * SR)
    j = min(len(buf), i + len(sig))
    if i < len(buf):
        buf[i:j] += sig[: j - i]


def pad_note(freq, length):
    n = int((length + 1.2) * SR)
    t = np.arange(n) / SR
    s = sum(np.sin(2 * np.pi * freq * (1 + det) * t + ph)
            for det, ph in ((-0.004, 0), (0.0, 1.3), (0.005, 2.1)))
    s += 0.3 * np.sin(2 * np.pi * freq * 2 * t)
    return s / 3.3 * env(n, 0.35, 0.3, 0.8, 1.2, length)


def pluck(freq, length=0.45, bright=1.0):
    n = int(length * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * freq * t) + 0.35 * bright * np.sin(2 * np.pi * freq * 2 * t) \
        + 0.12 * bright * np.sin(2 * np.pi * freq * 3 * t)
    return s * np.exp(-t * 9) * np.minimum(1, t / 0.004)


def bell(freq, length=1.6):
    n = int(length * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * freq * 2.76 * t) * np.exp(-t * 4) \
        + 0.25 * np.sin(2 * np.pi * freq * 5.4 * t) * np.exp(-t * 7)
    return s * np.exp(-t * 2.6) * np.minimum(1, t / 0.003)


def kick():
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 50 + 70 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def hat():
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    x = rng.standard_normal(n)
    x = x - lowpass(x, 6000)
    return x * np.exp(-t * 70)


def whoosh(length=0.7, rise=True):
    n = int(length * SR)
    t = np.arange(n) / SR
    x = lowpass(rng.standard_normal(n), 2500)
    shape = np.sin(np.pi * t / length) ** 2
    if rise:
        shape *= np.linspace(0.4, 1, n)
    return x * shape


music = np.zeros((N, 2))
sfx = np.zeros((N, 2))


def put(buf, sig, t, gain=1.0, pan=0.0):
    l, r = gain * np.sqrt((1 - pan) / 2), gain * np.sqrt((1 + pan) / 2)
    add(buf[:, 0], sig * l, t)
    add(buf[:, 1], sig * r, t)


# Am – F – C – G, по такту (4 доли = 2 с)
CHORDS = [[57, 60, 64], [53, 57, 60], [48, 55, 60, 64], [55, 59, 62]]
BASS = [45, 41, 48, 43]

for bar in range(11):
    t0 = bar * 2.0
    ch = CHORDS[bar % 4]
    # пэд
    for m in ch:
        put(music, pad_note(hz(m), 2.0), t0, 0.07)
    # бас на каждую долю, мягкий
    for b in range(4):
        tb = t0 + b * BEAT
        if tb >= 2.0:
            put(music, pluck(hz(BASS[bar % 4]), 0.45, 0.4), tb, 0.22)
    # арпеджио восьмыми с 3-й секунды
    if t0 >= 2.0:
        arp = [ch[0] + 12, ch[1] + 12, ch[2] + 12, ch[1] + 12]
        for k in range(8):
            ta = t0 + k * BEAT / 2
            if 2.9 <= ta < 21.0:
                put(music, pluck(hz(arp[k % 4]), 0.3, 0.8), ta, 0.05, pan=0.35 if k % 2 else -0.35)
    # ударные с 6-й секунды (сцена «Интересы»), тише в финале
    for b in range(4):
        tb = t0 + b * BEAT
        if 6.0 <= tb < 20.5:
            put(music, kick(), tb, 0.30 if b % 2 == 0 else 0.18)
        if 6.0 <= tb < 20.5:
            put(music, hat(), tb + BEAT / 2, 0.05, pan=0.2)

# «Крючок»: пульс пэда, в котором суетятся тихие плинки — поток постов
for k in range(24):
    tk = 0.1 + k * 0.12
    put(sfx, pluck(hz([69, 72, 76, 79][k % 4] + 12), 0.2, 0.3), tk, 0.018, pan=(k % 5 - 2) / 3)

# Раскрытие: реклама гаснет (нисходящий шорох), логотип — аккорд-колокольчик
put(sfx, whoosh(0.8, rise=False), 3.05, 0.05)
for i, m in enumerate([60, 64, 67, 72]):
    put(sfx, bell(hz(m + 12)), 3.95 + i * 0.03, 0.05, pan=(i - 1.5) / 3)

# Переходы: мягкий шорох, заканчивается на смене сцены
for tc in (5.6, 9.62, 14.62, 17.62):
    put(sfx, whoosh(0.5), tc, 0.035)

# Подсветка строк фильтра: ноты ля минора вверх
for i in range(6):
    put(sfx, pluck(hz([69, 72, 76, 81, 79, 76][i] + 12), 0.25, 0.4), 7.0 + i * 0.28, 0.035)

# Журнал: тик на каждую строку; «ИНТЕРЕСНО» — выше и чуть ярче
LOG = "hynnyhnyn"
for i, kind in enumerate(LOG):
    tl = 10.55 + i * 0.46
    if kind == "y":
        put(sfx, pluck(hz(84), 0.3, 0.6), tl + 0.22, 0.05, pan=0.2)
    elif kind == "n":
        put(sfx, pluck(hz(76), 0.2, 0.2), tl + 0.22, 0.025, pan=-0.2)
    else:
        put(sfx, pluck(hz(69), 0.2, 0.3), tl, 0.03)

# Доставка: по колокольчику на пост, вверх по до мажору
for i, (tm, m) in enumerate(zip((15.45, 16.0, 16.55), (72, 76, 79))):
    put(sfx, bell(hz(m + 12), 1.2), tm, 0.06, pan=(i - 1) * 0.3)

# Финал: широкий аккорд до мажора под логотип
for i, m in enumerate([48, 55, 60, 64, 67, 72]):
    put(music, pad_note(hz(m), 1.4), 20.5, 0.06)
    put(sfx, bell(hz(m + 12), 2.0), 20.55 + i * 0.025, 0.028, pan=(i - 2.5) / 4)

# Сведение: эффекты под музыкой, лёгкое «эхо» для общего пространства
mix = music + sfx
delay = int(0.375 * SR)
wet = np.zeros_like(mix)
wet[delay:] = mix[:-delay] * 0.18
wet[:, [0, 1]] = wet[:, [1, 0]]          # пинг-понг
mix = mix + wet

# общая форма: вступление, затухание в конце
t = np.arange(N) / SR
fade = np.minimum(1, t / 0.08) * np.clip((DUR - t) / 1.0, 0, 1) ** 1.5
mix *= fade[:, None]

# мягкий лимитер
peak = np.max(np.abs(mix))
mix = mix / peak * 0.9
mix = np.tanh(mix * 1.3) / np.tanh(1.3) * 0.89

with wave.open("audio.wav", "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix * 32767).astype("<i2").tobytes())
print("ok", round(float(np.sqrt(np.mean(mix ** 2))), 3))
