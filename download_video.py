import yt_dlp

def download_video(url):
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',  # Tải video và âm thanh tốt nhất có sẵn
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',  # Chuyển đổi định dạng video sau khi tải xong
            'preferedformat': 'mp4',  # Định dạng video bạn muốn (ở đây là mp4)
        }],
        'outtmpl': '%(title)s.%(ext)s',  # Lưu video với tên tự động theo tiêu đề
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

# Nhập link video và gọi hàm download_video
video_url = input("Nhập liên kết video: ")
download_video(video_url)
