# Contributing

## Project Structure

```
├── main.py          # Entry point
├── version.py       # Version string
├── core/            # Device communication (USB, HDLC, diag protocol)
├── gui/             # UI components (one file per tab)
```

## Code Style

All Python code is formatted with [Black](https://github.com/psf/black) using default settings (line length 88).

Please, format before committing:

```bash
pip install black
black .
```

## Guidelines

- Keep GUI logic in `gui/`, protocol/device logic in `core/`.
- One class per file where possible.
- Comments should explain _why_, not _what_.
- Test on a real device before submitting changes that touch `core/`.
