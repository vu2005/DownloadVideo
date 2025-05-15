from flask import Flask, render_template, request, redirect, url_for, session, flash
import yt_dlp
import os
import uuid
import threading
import time
from datetime import datetime
import json
import subprocess

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Lưu trữ trạng thái tải xuống
download_status = {}

def download_progress_hook(d):
    """Theo dõi tiến trình tải xuống"""
    download_id = d.get('download_id')
    if download_id is None:
        return
    
    if d['status'] == 'downloading':
        try:
            percent = d.get('_percent_str', 'N/A')
            speed = d.get('_speed_str', 'N/A')
            eta = d.get('_eta_str', 'N/A')
            
            download_status[download_id].update({
                'percent': percent,
                'speed': speed,
                'eta': eta,
                'status': 'downloading'
            })
        except:
            pass
    elif d['status'] == 'finished':
        download_status[download_id].update({
            'status': 'processing',  # Status changed to processing for post-processing
            'percent': '100%',
            'completed_time': datetime.now().strftime('%H:%M:%S')
        })
    elif d['status'] == 'error':
        download_status[download_id].update({
            'status': 'error',
            'error_message': d.get('error', 'Lỗi không xác định')
        })

def post_process_video(input_path, output_path, logo_path):
    """Post-process video: flip horizontally and overlay logo for first 3 seconds"""
    try:
        # Create a temporary file for the flipped video
        temp_path = input_path + "_temp.mp4"
        
        # Flip the video horizontally using FFmpeg
        flip_cmd = [
            'ffmpeg', '-i', input_path, '-vf', 'hflip', '-c:a', 'copy', temp_path
        ]
        subprocess.run(flip_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Overlay the logo for the first 3 seconds
        overlay_cmd = [
            'ffmpeg', '-i', temp_path, '-i', logo_path,
            '-filter_complex', 
            '[1:v]format=rgba [logo]; [0:v][logo]overlay=10:10:enable=\'between(t,0,3)\'',
            '-c:a', 'copy', output_path
        ]
        subprocess.run(overlay_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Clean up temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)

        return True
    except subprocess.CalledProcessError as e:
        raise Exception(f"FFmpeg error: {e.stderr.decode() if e.stderr else str(e)}")
    except Exception as e:
        raise Exception(f"Post-processing error: {str(e)}")

def download_video(url, download_path, format_option, download_id):
    """Tải xuống video và xử lý hậu kỳ (lật video và thêm logo)"""
    
    # Thiết lập các tùy chọn dựa trên định dạng được chọn
    if format_option == 'mp3':
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': os.path.join(download_path, '%(title)s.%(ext)s'),
            'progress_hooks': [download_progress_hook],
        }
    else:  # mp4 hoặc các định dạng khác
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': format_option,
            }],
            'outtmpl': os.path.join(download_path, '%(title)s.%(ext)s'),
            'progress_hooks': [download_progress_hook],
        }
    
    # Thêm ID tải xuống trực tiếp vào progress_hook
    ydl_opts['download_id'] = download_id
    
    try:
        # Cập nhật trạng thái bắt đầu
        download_status[download_id].update({
            'status': 'starting',
            'start_time': datetime.now().strftime('%H:%M:%S')
        })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Cập nhật thông tin video trước khi tải
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Video không xác định')
            download_status[download_id].update({
                'title': title,
                'thumbnail': info.get('thumbnail', '')
            })
            
            # Bắt đầu tải xuống
            ydl.process_ie_result(info, download=True)
            
            # Lấy đường dẫn file đã tải
            downloaded_file = os.path.join(download_path, f"{title}.{format_option}")
            
            # Chỉ xử lý hậu kỳ nếu không phải định dạng mp3
            if format_option != 'mp3':
                logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static/logo.png")
                if not os.path.exists(logo_path):
                    raise Exception("Logo file not found. Please provide a valid logo path.")
                
                # Đường dẫn file đầu ra sau khi xử lý
                processed_file = os.path.join(download_path, f"{title}_processed.{format_option}")
                
                # Xử lý hậu kỳ: lật video và thêm logo
                post_process_video(downloaded_file, processed_file, logo_path)
                
                # Xóa file gốc và đổi tên file đã xử lý thành tên gốc
                if os.path.exists(downloaded_file):
                    os.remove(downloaded_file)
                os.rename(processed_file, downloaded_file)
                
                # Cập nhật trạng thái hoàn thành
                download_status[download_id].update({
                    'status': 'finished',
                    'completed_processing_time': datetime.now().strftime('%H:%M:%S')
                })
            
        return True
    except Exception as e:
        # Cập nhật lỗi
        download_status[download_id].update({
            'status': 'error',
            'error_message': str(e)
        })
        return False

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Kiểm tra file - bắt buộc phải có file .txt
        if 'url_file' not in request.files or not request.files['url_file'].filename:
            flash('Vui lòng tải lên file .txt chứa các liên kết video', 'danger')
            return redirect(url_for('index'))
            
        file = request.files['url_file']
        if not file.filename.endswith('.txt'):
            flash('Chỉ hỗ trợ file .txt', 'danger')
            return redirect(url_for('index'))
        
        # Đọc urls từ file txt
        file_content = file.read().decode('utf-8')
        video_urls = [url.strip() for url in file_content.split('\n') if url.strip()]
        
        if not video_urls:
            flash('File không chứa liên kết nào. Vui lòng kiểm tra lại.', 'danger')
            return redirect(url_for('index'))
        
        format_option = request.form['format']
        download_path = request.form['download_path']
        
        # Kiểm tra đường dẫn tải xuống
        if not download_path:
            download_path = os.path.join(os.path.expanduser('~'), 'Downloads')
        
        # Đảm bảo thư mục tải xuống tồn tại
        if not os.path.exists(download_path):
            try:
                os.makedirs(download_path)
            except:
                flash(f'Không thể tạo thư mục {download_path}. Vui lòng chọn thư mục khác.', 'danger')
                return redirect(url_for('index'))
        
        # Lưu thông tin tải xuống vào session
        download_ids = []
        for url in video_urls:
            download_id = str(uuid.uuid4())
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
            
            # Tải xuống trong một luồng riêng biệt
            thread = threading.Thread(
                target=download_video, 
                args=(url, download_path, format_option, download_id)
            )
            thread.daemon = True
            thread.start()
        
        # Lưu IDs vào session
        session['download_ids'] = download_ids
        
        return redirect(url_for('download_status_page'))
    
    return render_template('index.html')

@app.route('/download_status')
def download_status_page():
    """Trang hiển thị trạng thái tải xuống"""
    download_ids = session.get('download_ids', [])
    return render_template('download_status.html', download_ids=download_ids, download_status=download_status)

@app.route('/check_status')
def check_status():
    """API để kiểm tra trạng thái tải xuống"""
    download_ids = session.get('download_ids', [])
    status_data = {id: download_status.get(id, {}) for id in download_ids}
    return json.dumps(status_data)

@app.route('/download_complete')
def download_complete():
    """Trang hoàn tất tải xuống"""
    return render_template('download_complete.html')

if __name__ == '__main__':
    app.run(debug=True)