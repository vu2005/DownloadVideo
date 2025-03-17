from flask import Flask, render_template, request, redirect, url_for
import yt_dlp

app = Flask(__name__)

def download_video(url):
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',  # Tải video và âm thanh tốt nhất có sẵn
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',  # Chuyển đổi định dạng video sau khi tải xong
            'preferedformat': 'mp4',  # Định dạng video bạn muốn (ở đây là mp4)
        }],
        'outtmpl': 'D:\download-video\Video\%(title)s.%(ext)s',  # Lưu video với tên tự động theo tiêu đề
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        video_url = request.form["url"]
        download_video(video_url)
        return redirect(url_for("download_complete"))

    return render_template("index.html")

@app.route("/download_complete")
def download_complete():
    return render_template("download_complete.html")

if __name__ == "__main__":
    app.run(debug=True)
