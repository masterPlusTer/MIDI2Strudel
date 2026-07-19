# Experimental converters

This folder contains research prototypes.

## Multi-track converter

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
