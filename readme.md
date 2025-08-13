# Social Media Video & Audio Downloader

A simple Windows app that lets you download videos and audio from:
YouTube, Facebook, Instagram (Reels included), TikTok, Twitter (X), Reddit, Pinterest, Twitch, SoundCloud, Vimeo, Bilibili, Mixcloud, Rumble, Odnoklassniki (OK.ru), TED Talks — all in **one program**.

No coding required. Just follow the steps below.

---

## Features

* **Best Quality Toggle** → Download the highest quality audio + video automatically, or manually choose from a quality list after checking what's available.
* **Partial Download Time Picker** → Select start and end times in hh\:mm\:ss format without typing.
* **Resume & Retry** → Downloads automatically resume if interrupted.
* **Thumbnail & Metadata Preview** → See the title, thumbnail, uploader, and duration before downloading.
* **Post-download Metadata Editing** → Audio files automatically get correct artist/title info.
* **Custom Download Folder** → Choose where your files are saved.
* **Dark Mode Support** → Toggle between light and dark themes.
* **Clipboard Link Detection** → Copy any supported video link, and the app will ask if you want to download it.
* **Drag & Drop Support** → Drop multiple links directly into the app.
* **Batch Download** → Add multiple videos to a queue and download all at once.

---

## Requirements

Before running the program:

1. **Install Python**

   * Download from [https://www.python.org/downloads/windows/](https://www.python.org/downloads/windows/)
   * During install, **check the box** that says "Add Python to PATH".

2. **Install Dependencies**

   * Open the folder where you downloaded this program.
   * Hold **Shift** + Right-click in the empty space → Click **Open PowerShell window here** (or Command Prompt).
   * Type:

     ```bash
     pip install -r requirements.txt
     ```

3. **Extra Tools (Optional but Recommended)**

   * **FFmpeg**: Needed for merging video + audio and partial downloads.

     * Download from: [https://www.gyan.dev/ffmpeg/builds/](https://www.gyan.dev/ffmpeg/builds/)
     * Unzip it and put `ffmpeg.exe` into the program’s `tools` folder.
   * **aria2c**: For faster downloads (optional).

     * Download from: [https://aria2.github.io/](https://aria2.github.io/)
     * Put `aria2c.exe` into the `tools` folder.

---

## How to Run

1. **Download the Program**

   * Click the green **Code** button on this page.
   * Select **Download ZIP** and extract it anywhere (e.g., Desktop).

2. **Open the App**

   * Inside the extracted folder, double-click:

     ```
     run.bat
     ```

     This will open the downloader window.

---

## 📌 How to Use

1. **Automatic Clipboard Detection**

   * Copy a video link (YouTube, Instagram, TikTok, etc.).
   * The app will ask if you want to add it to the download list.

2. **Add Links Manually**

   * Paste links into the app or drag and drop them.

3. **Choose Quality**

   * If **Best Quality** is ON → Downloads highest audio + video.
   * If OFF → You’ll see available formats with size estimates and can choose one.

4. **Partial Download**

   * Use the time picker to set start and end times for downloading only a section of the video.

5. **Download**

   * Click **Start Download**.
   * Progress bar shows speed, ETA, retries.
   * Files appear in your chosen folder when done.

---

## 💡 Tips

* Keep **FFmpeg** in the `tools` folder for best results.
* If something doesn’t download, check if the platform changed — update yt-dlp with:

  ```bash
  pip install -U yt-dlp
  ```

---

## 🛠 Supported Platforms

* YouTube
* Facebook
* Instagram (including Reels)
* TikTok
* Twitter (X)
* Reddit
* Pinterest
* Twitch
* SoundCloud
* Vimeo
* Bilibili
* Mixcloud
* Rumble
* Odnoklassniki (OK.ru)
* TED Talks

---

**Enjoy downloading!**
