from flask import Flask, render_template, request, redirect, url_for, session, flash
import yt_dlp
import os
import uuid
import threading
import time
from datetime import datetime
import json
import subprocess
import validators
import logging

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Thiết lập logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Lưu trữ trạng thái tải xuống
download_status = {}
status_lock = threading.Lock()  # Lock để đảm bảo thread-safe

def download_progress_hook(d):
    """Theo dõi tiến trình tải xuống"""
    download_id = d.get('download_id')
    if download_id is None:
        return

    status_update = {}
    if d['status'] == 'downloading':
        try:
            status_update = {
                'percent': d.get('_percent_str', 'N/A'),
                'speed': d.get('_speed_str', 'N/A'),
                'eta': d.get('_eta_str', 'N/A'),
                'status': 'downloading'
            }
        except:
            pass
    elif d['status'] == 'finished':
        status_update = {
            'status': 'processing',
            'percent': '100%',
            'completed_time': datetime.now().strftime('%H:%M:%S')
        }
    elif d['status'] == 'error':
        status_update = {
            'status': 'error',
            'error_message': d.get('error', 'Lỗi không xác định')
        }

    with status_lock:
        if download_id in download_status:
            download_status[download_id].update(status_update)

def post_process_video(input_path, output_path, logo_path):
    """Post-process video: overlay logo for first 5 seconds"""
    try:
        if not os.path.exists(logo_path):
            raise FileNotFoundError("Logo file not found")

        # FFmpeg command để thêm logo trong 5 giây đầu
        overlay_cmd = [
            'ffmpeg', '-y',  # Ghi đè file đầu ra nếu tồn tại
            '-i', input_path,
            '-i', logo_path,
            '-filter_complex',
            '[1:v]format=rgba[logo];[0:v][logo]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)*0.9:enable=\'between(t,5,10)\'',
            '-c:a', 'copy',
            output_path
        ]
        result = subprocess.run(overlay_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        logger.info(f"FFmpeg output: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr}")
        raise Exception(f"FFmpeg error: {e.stderr}")
    except Exception as e:
        logger.error(f"Post-processing error: {str(e)}")
        raise Exception(f"Post-processing error: {str(e)}")

def download_video(url, download_path, format_option, download_id):
    """Tải xuống video và xử lý hậu kỳ"""
    unique_id = str(uuid.uuid4())  # ID duy nhất để tránh xung đột file
    temp_file = os.path.join(download_path, f"temp_{unique_id}.%(ext)s")
    processed_file = os.path.join(download_path, f"processed_{unique_id}.%(ext)s")

    ydl_opts = {
        'outtmpl': temp_file,
        'progress_hooks': [download_progress_hook],
        'download_id': download_id
    }

    if format_option == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        ydl_opts.update({
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': format_option,
        })

    try:
        with status_lock:
            download_status[download_id].update({
                'status': 'starting',
                'start_time': datetime.now().strftime('%H:%M:%S')
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Video không xác định').replace('/', '_').replace('\\', '_')  # Sanitize title
            download_status[download_id].update({
                'title': title,
                'thumbnail': info.get('thumbnail', '')
            })

            ydl.process_ie_result(info, download=True)

            downloaded_file = temp_file.replace('%(ext)s', format_option)
            final_file = os.path.join(download_path, f"{title}.{format_option}")

            if format_option != 'mp3':
                logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static/logo.png")
                processed_file = processed_file.replace('%(ext)s', format_option)

                post_process_video(downloaded_file, processed_file, logo_path)

                # Đổi tên file đã xử lý thành tên cuối cùng
                if os.path.exists(processed_file):
                    os.rename(processed_file, final_file)
                else:
                    raise Exception("Processed file not found")
                
                # Xóa file tạm
                if os.path.exists(downloaded_file):
                    os.remove(downloaded_file)
            else:
                # Đối với MP3, chỉ đổi tên file
                if os.path.exists(downloaded_file):
                    os.rename(downloaded_file, final_file)

            with status_lock:
                download_status[download_id].update({
                    'status': 'finished',
                    'completed_processing_time': datetime.now().strftime('%H:%M:%S')
                })

        return True
    except Exception as e:
        logger.error(f"Download error for {url}: {str(e)}")
        with status_lock:
            download_status[download_id].update({
                'status': 'error',
                'error_message': str(e)
            })
        # Cleanup
        for f in [temp_file.replace('%(ext)s', format_option), processed_file.replace('%(ext)s', format_option)]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass
        return False

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'url_file' not in request.files or not request.files['url_file'].filename:
            flash('Vui lòng tải lên tệp .txt chứa các liên kết video', 'danger')
            return redirect(url_for('index'))

        file = request.files['url_file']
        if not file.filename.endswith('.txt'):
            flash('Chỉ hỗ trợ tệp .txt', 'danger')
            return redirect(url_for('index'))

        file_content = file.read().decode('utf-8', errors='ignore')
        video_urls = [url.strip() for url in file_content.split('\n') if url.strip() and validators.url(url.strip())]

        if not video_urls:
            flash('Tệp không chứa liên kết hợp lệ. Vui lòng kiểm tra lại.', 'danger')
            return redirect(url_for('index'))

        format_option = request.form.get('format', 'mp4')
        download_path = request.form.get('download_path', os.path.join(os.path.expanduser('~'), 'Downloads'))

        if not os.path.exists(download_path):
            try:
                os.makedirs(download_path)
            except Exception as e:
                flash(f'Không thể tạo thư mục {download_path}: {str(e)}', 'danger')
                return redirect(url_for('index'))

        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static/logo.png")
        if format_option != 'mp3' and not os.path.exists(logo_path):
            flash('Tệp logo không tồn tại trong thư mục static.', 'danger')
            return redirect(url_for('index'))

        download_ids = []
        for url in video_urls:
            download_id = str(uuid.uuid4())
            with status_lock:
                download_status[download_id] = {
                    'url': url,
                    'format': format_option,
                    'download_path': download_path,
                    'status': 'queued',
                    'percent': '0%',
                    'speed': 'N/A',
                    'eta': 'N/A',
                    'title': 'Đang xử lý...',
                    'thumbnail': '',
                    'queued_time': datetime.now().strftime('%H:%M:%S')
                }
            download_ids.append(download_id)

            thread = threading.Thread(
                target=download_video,
                args=(url, download_path, format_option, download_id)
            )
            thread.daemon = True
            thread.start()

        session['download_ids'] = download_ids
        return redirect(url_for('download_status_page'))

    return render_template('index.html')

@app.route('/download_status')
def download_status_page():
    download_ids = session.get('download_ids', [])
    return render_template('download_status.html', download_ids=download_ids, download_status=download_status)

@app.route('/js/download_status.js')
def download_status_js():
    with open('static/js/download_status.js', 'r') as f:
        return f.read(), 200, {'Content-Type': 'application/javascript'}

@app.route('/check_status')
def check_status():
    download_ids = session.get('download_ids', [])
    with status_lock:
        status_data = {id: download_status.get(id, {}) for id in download_ids}
    return json.dumps(status_data)

@app.route('/download_complete')
def download_complete():
    return render_template('download_complete.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)