"""Run in a user-controlled terminal; never prints the secret."""
import getpass
import warnings
from pathlib import Path
ENV_FILE = Path(__file__).resolve().parent / ".env"

def main():
    print("OpenAI API key setup (saved locally to Git-ignored .env)")
    if ENV_FILE.exists():
        print("The OPENAI_API_KEY entry will be replaced; other settings are kept.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            key = getpass.getpass("Paste API key (hidden), then press Enter: ").strip()
        except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
            print("Setup cancelled. Please run this script in an interactive terminal.")
            return
    if not key.startswith("sk-") or any(c.isspace() for c in key):
        print("Invalid key format. Nothing saved.")
        return
    lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines() if ENV_FILE.exists() else []
    lines = [line for line in lines if line.partition("=")[0].strip() != "OPENAI_API_KEY"]
    lines.append("OPENAI_API_KEY=" + key)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Saved. Restart the server, then refresh the app. API connectivity is not yet verified.")

if __name__ == "__main__":
    main()
