# SplitSnap

SplitSnap is an AI receipt reader and bill splitter built with Streamlit and Gemini. Upload a receipt photo or describe a bill, review the extracted items and total, split evenly or assign line items to specific people, then email yourself a concise conversation summary.

## Features

- Gemini chat with receipt-photo and text input.
- Item, tax, tip, and total extraction when visible; uncertain values should be checked.
- Even split with cent-accurate rounding, or item-by-item allocation among named participants.
- Optional Gmail summary delivery using SMTP and a Gmail App Password.
- Secrets are read from Streamlit configuration and excluded from Git.

## Requirements

- Python 3.9 or newer.
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/).
- For email summaries, Gmail with 2-Step Verification and an App Password. Email sending is optional; chat and splitting do not use Gmail.

## Run locally (Windows PowerShell)

1. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install the app packages:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in your Gemini key. To enable email, also add your Gmail address and its App Password.

4. Start the app:

   ```powershell
   streamlit run app.py
   ```

Then open the local URL shown in the terminal. The real `secrets.toml` is ignored by Git; commit only the example template.

## Use the app

1. Enter your name and the email address where you want the summary delivered.
2. Ask a question about a receipt or attach a JPG/PNG photo in the chat input.
3. Review the AI response and verify the extracted amounts.
4. Choose **Evenly** to divide a total across the group, or **By item** to select who shared each line.
5. Select **Email summary** when you want the conversation and current split emailed to you.

For an item-based split, list participants as comma-separated names. A line with no matching names is shared by everyone. Add tax, tip, or other charges as rows if they are not already part of the line-item amounts.

## Deploy

Push the project to a GitHub repository without `.streamlit/secrets.toml`. In Streamlit Community Cloud, select `app.py` as the entry point and add the same secret values in the app's **Settings → Secrets** panel. Never publish API keys, Gmail App Passwords, or receipt photos in a repository.

## Tests

Run the standard-library unit tests with:

```powershell
python -m unittest
```

## Privacy and accuracy

Receipt images and chat content are sent to Google's Gemini API for analysis. Do not upload receipts containing information you do not want processed by the API. AI extraction is an estimate: check the receipt and the final split before sending or paying. Gmail delivery is only initiated when you click the email button.