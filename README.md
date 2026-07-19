# MIDI2Strudel

⚠ **This project is experimental.** The goal is to generate readable and editable Strudel code rather than perfectly reproduce MIDI playback.

> An experimental Python project for converting MIDI files into editable Strudel code.

Unlike a traditional MIDI player, the goal of this project is **not** to reproduce MIDI as faithfully as possible.

The objective is to generate **human-readable Strudel code** that musicians can understand, edit, remix and learn from.

The project is still experimental, and many interesting problems remain unsolved.

---

# Features

Current capabilities include:

- Reading Standard MIDI Files (.mid)
- Matching Note On / Note Off events
- Automatic quantization
- Basic monophonic voice separation
- Bar-based Strudel generation
- Exporting editable Strudel code
- Saving generated files to the `output/` directory

---

# Installation

Requires Python 3.10 or newer.

Install the dependencies:

```bash
pip install -r requirements.txt
```

---

# Recommended Workflow

The current version works **best with individual MIDI tracks** rather than complete multi-track arrangements.

For orchestral pieces or complex MIDI files, the recommended workflow is:

```
Original MIDI
        │
        ▼
Split into individual instrument tracks
        │
        ▼
Convert each track separately
        │
        ▼
Combine the generated Strudel patterns manually
```

Most MIDI editors (MuseScore, Reaper, Logic, Cubase, etc.) can export individual tracks as separate MIDI files.

Although the converter can process complete MIDI files, the generated output quickly becomes difficult to read because automatic reconstruction of multiple independent musical voices is still an open problem.

Working with individual tracks produces significantly cleaner and more editable Strudel code.

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

This project explores how to convert MIDI into Strudel code that feels natural to read and edit.

The emphasis is on readability and editability rather than perfect playback accuracy.

For example, instead of generating a single enormous sequence of note events, the converter now generates **bar-based Strudel patterns**, making the output much easier to understand and modify.

Long-term goals include recognizing musical structure rather than simply translating MIDI events.

---

# Why is this difficult?

Converting MIDI into editable Strudel code is much harder than simply replaying MIDI events.

Several interesting problems have appeared during development.

---

## Polyphony

Splitting a MIDI file into separate tracks is usually the best starting point.

However, individual MIDI tracks can still contain multiple overlapping musical voices. While this is perfectly valid for playback, it becomes a major challenge when the goal is to generate clean, editable Strudel code.

Finding a good voice separation strategy remains one of the central problems this project is trying to solve.

Current challenges include:

- automatic voice separation
- preserving overlapping notes
- assigning notes to musically coherent voices

---

## Melody Extraction

The highest note is not necessarily the melody.

A convincing melody extractor probably needs to recognize musical phrases instead of selecting notes purely by pitch.

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

This project intentionally prefers readable code over raw MIDI data.

The objective is not merely to generate executable Strudel.

The generated code should remain understandable, editable and educational for human musicians.

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
- Generating one enormous Strudel pattern is far less useful than generating structured musical sections.

---

# Current Limitations

The converter currently assumes that **one input file represents one musical part**.

It is **not yet intended** to reconstruct complete orchestral scores automatically.

Complex MIDI files containing many instruments and overlapping voices usually produce cluttered output. This is expected and is one of the primary research problems the project aims to address.

---

# Future Work

Possible future improvements include:

- Better voice separation
- Chord detection
- Phrase detection
- Motif recognition
- Pattern simplification
- Repeated pattern detection
- Improved pattern generation
- Full tempo map support
- Cleaner Strudel syntax
- Live MIDI capture
- Better handling of tempo changes
- Round-trip editing

---

# What this project is NOT

This project is **not** intended to become a perfect MIDI player.

There are already excellent MIDI players available.

The purpose here is different:

Generate Strudel code that preserves as much musical information as possible while remaining readable, editable and useful for musicians.

---

## Experimental Multi-track Converter

The repository also includes an experimental multi-track converter:

```bash
python midi_to_strudel_multitrack_experimental.py song.mid
```

This version processes a complete MIDI file automatically.

It generates:

* One Strudel file for each MIDI track containing notes
* A combined Strudel file containing the complete arrangement

Example output:

```text
output/
└── song/
    ├── song_track_01.strudel
    ├── song_track_02.strudel
    ├── song_track_09.strudel
    └── song_combined.strudel
```

The combined arrangement preserves the relative timing between tracks.

### Important limitation

This converter prioritizes stable playback over exact MIDI fidelity.

Complex MIDI arrangements may generate a very large number of simultaneous voices. This can overload Strudel or the browser's WebAudio engine, causing distortion or audio playback to stop.

To reduce this problem, the experimental converter:

* Limits the number of voices generated for each track
* Shortens sample tails
* Reduces the gain of the combined arrangement
* Handles percussion tracks separately
* Removes global leading silence while preserving track synchronization

As a result, the combined output may sound less faithful to the original MIDI.

For more accurate and editable results, converting individual tracks separately with the main converter is still recommended.


## Experimental expressive multi-track converter

The repository also includes an experimental expressive converter:

```bash
python midi_to_strudel_multitrack_expressive.py song.mid
```

Like the experimental multi-track converter, this version automatically processes an entire MIDI file, exports one Strudel file for each musical track, and generates a synchronized combined arrangement.

In addition, it attempts to preserve more of the original MIDI performance by translating expressive information into Strudel patterns.

Current features:

- Automatic track detection
- One Strudel file per MIDI track
- Automatic combined arrangement
- Velocity preservation
- Sustain pedal support (CC64)
- Channel volume (CC7)
- Expression (CC11)
- Pan (CC10)
- Higher timing resolution (1/32)
- Voice limiting for browser stability

### Design goals

Unlike the standard converter, this prototype focuses on preserving musical expression rather than producing the cleanest possible Strudel code.

The generated output is intentionally more complex in exchange for a performance that better resembles the original MIDI.

### Limitations

This is still an experimental research prototype.

Some expressive MIDI events cannot yet be represented perfectly in Strudel, and dense arrangements may still lose detail because voice limiting is applied to keep playback stable inside the browser.



# Contributions

Ideas, bug reports, discussions and pull requests are very welcome.

If you have experience with MIDI, music theory, Strudel, TidalCycles or algorithmic composition, your feedback would be greatly appreciated.

---

# Looking for Feedback

I'm especially interested in ideas about:

- Voice separation
- Melody extraction
- Better Strudel representations
- Music theory approaches
- Pattern simplification
- Musical structure detection

---

# License

MIT License.
