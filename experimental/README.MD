# Experimental converters

This folder contains research prototypes.

## Multi-track converter


https://github.com/user-attachments/assets/e7b7651d-636a-4c04-b477-207418e72198


```bash
python midi_to_strudel_multitrack_experimental.py song.mid
```

Automatically separates a MIDI into individual Strudel tracks and generates a synchronized combined arrangement.

---

## Expressive multi-track converter

```bash
python midi_to_strudel_multitrack_expressive.py song.mid
```

Builds upon the multi-track converter and attempts to preserve expressive MIDI information such as:

- velocity
- sustain pedal
- channel volume
- expression
- pan

These prototypes prioritize experimentation over exact MIDI reproduction.

https://github.com/user-attachments/assets/d122915e-4c37-4c1e-a2bd-dd946bcbe2f4

