from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import json
from datetime import datetime
import cgi
import traceback

# 基础配置
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'voice')

# 从文件加载API密钥
def load_api_keys():
    try:
        with open('api_key.txt', 'r') as f:
            keys = json.load(f)
            return keys.get('api_key'), keys.get('admin_key')
    except Exception as e:
        print(f"Error loading API keys: {e}")
        return None, None

API_KEY, ADMIN_KEY = load_api_keys()

class CustomHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        """处理GET请求"""
        print(f"\n=== 处理GET请求 ===")
        print(f"请求路径: {self.path}")
        
        try:
            # 处理音频文件请求
            if self.path.startswith('/voice/'):
                self.handle_audio_file()
                return
                
            # 处理管理员API
            if self.path.startswith('/api/admin/uploads'):
                self.handle_admin_uploads()
                return
                
            # 处理静态文件
            if self.path == '/':
                self.path = '/index.html'
            elif self.path == '/admin':
                self.path = '/admin.html'

            # 获取文件路径
            if self.path.startswith('/'):
                file_path = os.path.join(STATIC_DIR, self.path[1:])
            else:
                file_path = os.path.join(STATIC_DIR, self.path)

            # 检查文件是否存在
            if os.path.exists(file_path) and os.path.isfile(file_path):
                with open(file_path, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', self.guess_type(file_path))
                self.send_header('Content-Length', len(content))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404, 'File not found')
        except Exception as e:
            print(f"Error: {e}")
            self.send_error(500, str(e))

    def handle_audio_file(self):
        """处理音频文件请求"""
        try:
            # 获取文件名
            file_name = os.path.basename(self.path)
            file_path = os.path.join(UPLOAD_DIR, file_name)
            
            print(f"请求音频文件: {file_path}")
            
            if os.path.exists(file_path) and os.path.isfile(file_path):
                with open(file_path, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'audio/mpeg')
                self.send_header('Content-Length', len(content))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(content)
                print(f"音频文件发送成功: {file_path}")
            else:
                print(f"音频文件不存在: {file_path}")
                self.send_error(404, "Audio file not found")
        except Exception as e:
            print(f"处理音频文件失败: {e}")
            self.send_error(500, str(e))

    def handle_admin_uploads(self):
        """处理管理员上传列表请求"""
        try:
            # 验证管理员密钥
            admin_key = self.headers.get('X-Admin-Key')
            if admin_key != ADMIN_KEY:
                self.send_error(401, 'Invalid admin key')
                return

            # 读取上传记录
            records = []
            if os.path.exists('upload_records.txt'):
                with open('upload_records.txt', 'r') as f:
                    for line in f:
                        try:
                            record = json.loads(line.strip())
                            records.append(record)
                        except:
                            continue

            # 发送响应
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response = {
                'code': 200,
                'message': 'success',
                'records': records
            }
            self.wfile.write(json.dumps(response).encode())
            
        except Exception as e:
            print(f"Admin API error: {e}")
            self.send_error(500, str(e))

    def do_DELETE(self):
        """处理DELETE请求"""
        print(f"\n=== 处理DELETE请求 ===")
        print(f"请求路径: {self.path}")
        
        if self.path.startswith('/api/admin/delete/'):
            try:
                # 验证管理员密钥
                admin_key = self.headers.get('X-Admin-Key')
                if admin_key != ADMIN_KEY:
                    self.send_error(401, 'Invalid admin key')
                    return

                # 获取文件名
                file_name = os.path.basename(self.path)
                file_path = os.path.join(UPLOAD_DIR, file_name)
                
                print(f"尝试删除文件: {file_path}")
                
                if os.path.exists(file_path):
                    # 删除文件
                    os.remove(file_path)
                    
                    # 更新记录文件
                    if os.path.exists('upload_records.txt'):
                        with open('upload_records.txt', 'r', encoding='utf-8') as f:
                            records = [json.loads(line) for line in f if line.strip()]
                        
                        # 过滤掉被删除的文件记录
                        records = [r for r in records if r.get('filename') != file_name]
                        
                        with open('upload_records.txt', 'w', encoding='utf-8') as f:
                            for record in records:
                                f.write(json.dumps(record, ensure_ascii=False) + '\n')
                    
                    # 发送成功响应
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    response = {
                        'code': 200,
                        'message': '文件删除成功'
                    }
                    self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
                    print(f"文件删除成功: {file_path}")
                else:
                    print(f"要删除的文件不存在: {file_path}")
                    self.send_error(404, "File not found")
            except Exception as e:
                print(f"删除文件失败: {e}")
                print(traceback.format_exc())
                self.send_error(500, str(e))
        else:
            self.send_error(404, "API not found")

    def do_OPTIONS(self):
        """处理OPTIONS请求"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, DELETE')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Admin-Key')
        self.end_headers()

    def do_POST(self):
        """处理POST请求"""
        print(f"\n=== 处理POST请求 ===")
        print(f"请求路径: {self.path}")
        
        if self.path == '/api/upload':
            try:
                # 获取Content-Length
                content_length = int(self.headers['Content-Length'])
                print(f"Content-Length: {content_length}")

                # 设置最大文件大小（例如50MB）
                max_file_size = 50 * 1024 * 1024
                if content_length > max_file_size:
                    self.send_error(413, "File too large")
                    return

                # 解析表单数据
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        'REQUEST_METHOD': 'POST',
                        'CONTENT_TYPE': self.headers['Content-Type'],
                    }
                )

                # 检查文件字段
                if 'file' not in form:
                    raise Exception('No file field in upload')

                # 获取文件项
                fileitem = form['file']
                if not fileitem.filename:
                    raise Exception('No file selected')

                print(f"接收到文件: {fileitem.filename}")

                # 生成安全的文件名
                filename = os.path.basename(fileitem.filename)
                safe_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
                filepath = os.path.join(UPLOAD_DIR, safe_filename)

                # 保存文件
                with open(filepath, 'wb') as f:
                    f.write(fileitem.file.read())

                file_size = os.path.getsize(filepath)
                print(f"文件已保存: {filepath} ({file_size} bytes)")

                # 记录上传信息
                record = {
                    'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'filename': safe_filename,
                    'original_filename': filename,
                    'size': file_size
                }

                with open('upload_records.txt', 'a', encoding='utf-8') as f:
                    f.write(json.dumps(record, ensure_ascii=False) + '\n')

                # 发送响应
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()

                response = {
                    'code': 200,
                    'message': '上传成功',
                    'data': {
                        'file_name': safe_filename,
                        'file_url': f'/voice/{safe_filename}',
                        'upload_time': record['datetime']
                    }
                }
                
                response_json = json.dumps(response, ensure_ascii=False)
                print(f"发送响应: {response_json}")
                self.wfile.write(response_json.encode('utf-8'))

            except Exception as e:
                print(f"上传错误: {e}")
                print(traceback.format_exc())
                self.send_error(500, str(e))
        else:
            self.send_error(404, 'API not found')

def run(port=8000):
    server_address = ('', port)
    httpd = HTTPServer(server_address, CustomHandler)
    print(f"Starting server on port {port}")
    print(f"Static directory: {STATIC_DIR}")
    print(f"Upload directory: {UPLOAD_DIR}")
    print(f"Admin key: {ADMIN_KEY}")  # 仅用于测试
    httpd.serve_forever()

if __name__ == '__main__':
    # 确保目录存在
    os.makedirs(STATIC_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # 启动服务器
    run()
