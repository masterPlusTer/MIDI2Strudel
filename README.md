# MIDI2Strudel

> An experimental Python project for converting MIDI files into editable Strudel code.

Unlike a traditional MIDI player, the goal of this project is **not** to reproduce MIDI as faithfully as possible.

The objective is to generate **human-readable Strudel code** that musicians can understand, edit, remix and learn from.

The project is still experimental and many interesting problems remain unsolved.

---

# Features

Current capabilities include:

- Reading Standard MIDI Files (.mid)
- Matching Note On / Note Off events
- Quantization
- Exporting Strudel code
- Saving generated files to the `output/` directory

---

# Installation

Requires Python 3.10 or newer.

Install the dependencies:

```bash
pip install -r requirements.txt
```

---

# Usage

Place one or more MIDI files in the project folder and simply run:

```bash
python midi_to_strudel.py
```

The generated Strudel file will appear in:

```
output/
```

---

# Project Goals

This project is exploring how to convert MIDI into code that feels natural inside Strudel.

The emphasis is on readability and editability rather than perfect playback accuracy.

Example goal:

Instead of generating something like:

```javascript
note("60 64 67 72 74 76 79")
```

the long-term goal is to generate patterns that preserve the musical structure and can easily be modified.

---

# Why is this difficult?

Converting MIDI into editable Strudel code is much harder than simply replaying MIDI events.

Several interesting problems have appeared during development.

## Polyphony

A single MIDI track can contain several independent musical voices.

Simply exporting notes in chronological order often destroys the musical structure.

Current research:

- automatic voice separation
- preserving overlapping notes

---

## Melody Extraction

The highest note is not necessarily the melody.

A convincing melody extractor probably needs to recognize musical phrases instead of selecting notes by pitch alone.

Current status:

Experimental.

---

## Quantization

Real performances rarely align perfectly with a fixed timing grid.

Choosing the right subdivision while preserving the musical feel remains an open problem.

---

## Tempo Changes

Many MIDI files contain multiple tempo changes.

Reading tempo events is relatively straightforward.

Representing them naturally inside Strudel is much harder.

---

## Human-readable Output

This project intentionally prefers readable code over raw data.

The goal is not merely to convert MIDI into something executable.

The generated Strudel should still be understandable by a human.

---

## Voice Reconstruction

One promising approach is separating overlapping notes into independent monophonic voices before generating Strudel.

For example:

```
Original MIDI

C ───────────────
    E ───────
        G ───

↓

Voice 1

C ───────────────

Voice 2

    E ───────

Voice 3

        G ───
```

These voices can later be combined using Strudel's `stack()`.

---

# Lessons Learned

Some assumptions that turned out to be wrong:

- The highest note is not always the melody.
- A MIDI track is not the same thing as a musical voice.
- Duration and note onset are different concepts.
- Quantization alone does not create readable music.
- A faithful MIDI conversion is not necessarily a good Strudel conversion.

---

# Future Work

Possible future improvements include:

- Better voice separation
- Chord detection
- Phrase detection
- Motif recognition
- Improved pattern generation
- Full tempo map support
- Cleaner Strudel syntax
- Live MIDI capture
- Better handling of tempo changes
- Round-trip editing

---

# What this project is NOT

This is **not** intended to become a perfect MIDI player.

There are already excellent MIDI players available.

The purpose of this project is different:

Generate Strudel code that preserves as much musical information as possible while remaining readable and editable by humans.

---

# Contributions

Ideas, bug reports, discussions and pull requests are very welcome.

If you have experience with MIDI, music theory, Strudel, TidalCycles or algorithmic composition, your feedback would be greatly appreciated.

---

# License

MIT License.
