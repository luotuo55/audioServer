import os
import json
import traceback
from http.server import SimpleHTTPRequestHandler, HTTPServer
import cgi
import uuid
import secrets  # 新增：用于生成安全的 API 密钥

print("Server script starting...")

# 设置存储静态文件的目录
STATIC_DIR = os.path.join(os.path.dirname(__file__), "public")
# 设置存储上传音频文件的目录
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "voice")

print(f"STATIC_DIR: {STATIC_DIR}")
print(f"UPLOAD_DIR: {UPLOAD_DIR}")

# 确保上传目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 使用环境变量设置 API 密钥，如果没有设置则生成一个
API_KEY = os.environ.get('API_KEY') or secrets.token_urlsafe(32)
print(f"API Key: {API_KEY}")

# 添加一个新的常量来定义文件访问的基础 URL
BASE_URL = os.environ.get('BASE_URL', 'http://localhost:8000')

class CustomHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        print("Initializing CustomHandler")
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self):
        print(f"Received GET request for: {self.path}")
        if self.path == '/':
            self.path = '/index.html'
        return super().do_GET()

    def do_POST(self):
        print(f"Received POST request to: {self.path}")
        if self.path == '/api/upload':
            # 验证 API 密钥
            if not self.verify_api_key():
                self.send_error(401, 'Unauthorized: Invalid API Key')
                return

            try:
                print("Processing API upload request")
                content_length = int(self.headers['Content-Length'])
                print(f"Content-Length: {content_length}")
                
                content_type = self.headers['Content-Type']
                print(f"Content-Type: {content_type}")
                
                if content_type.startswith('audio/'):
                    print("Receiving audio file")
                    file_extension = self.get_file_extension(content_type)
                    file_name = f"{uuid.uuid4()}.{file_extension}"
                    file_path = os.path.join(UPLOAD_DIR, file_name)
                    
                    with open(file_path, 'wb') as f:
                        f.write(self.rfile.read(content_length))
                    
                    print(f"File saved as: {file_path}")
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    
                    # 构建文件的访问 URL
                    file_url = f"{BASE_URL}/voice/{file_name}"
                    
                    response = json.dumps({
                        'message': 'File uploaded successfully',
                        'file_name': file_name,
                        'file_url': file_url
                    })
                    self.wfile.write(response.encode())
                    print("Response sent")
                    return
                else:
                    print(f"Unexpected content type: {content_type}")
                    self.send_error(400, 'Bad Request: Invalid content type')
                    return
            except Exception as e:
                print(f"Error during API file upload: {str(e)}")
                print(traceback.format_exc())
                self.send_error(500, f'Internal Server Error: {str(e)}')
                return
        elif self.path == '/upload':
            try:
                print("Processing upload request")
                content_length = int(self.headers['Content-Length'])
                print(f"Content-Length: {content_length}")
                
                content_type, _ = cgi.parse_header(self.headers['Content-Type'])
                print(f"Content-Type: {content_type}")
                
                if content_type == 'multipart/form-data':
                    print("Parsing multipart form data")
                    form = cgi.FieldStorage(
                        fp=self.rfile,
                        headers=self.headers,
                        environ={'REQUEST_METHOD': 'POST'}
                    )
                    print(f"Form fields: {list(form.keys())}")
                    
                    if 'audio' in form:
                        file_item = form['audio']
                        print(f"Received file: {file_item.filename}")
                        if file_item.filename:
                            file_path = os.path.join(UPLOAD_DIR, file_item.filename)
                            print(f"Saving file to: {file_path}")
                            with open(file_path, 'wb') as f:
                                f.write(file_item.file.read())
                            print("File saved successfully")
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/json')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            response = json.dumps({'message': 'File uploaded successfully'})
                            self.wfile.write(response.encode())
                            print("Response sent")
                            return
                        else:
                            print("File item has no filename")
                    else:
                        print("No 'audio' field in form data")
                else:
                    print(f"Unexpected content type: {content_type}")
            except Exception as e:
                print(f"Error during file upload: {str(e)}")
                print(traceback.format_exc())
                self.send_error(500, f'Internal Server Error: {str(e)}')
                return
            self.send_error(400, 'Bad Request: File not found in form data')
        else:
            self.send_error(404, 'Not Found')

    def do_OPTIONS(self):
        print("Received OPTIONS request")
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header("Access-Control-Allow-Headers", "X-Requested-With, Content-Type, X-API-Key")  # 添加 X-API-Key
        self.end_headers()

    def get_file_extension(self, content_type):
        # 映射 MIME 类型到文件扩展名
        mime_to_extension = {
            'audio/mpeg': 'mp3',
            'audio/wav': 'wav',
            'audio/ogg': 'ogg',
            'audio/x-m4a': 'm4a',
            'audio/aac': 'aac',
            'audio/flac': 'flac',
        }
        subtype = content_type.split('/')[-1]
        return mime_to_extension.get(content_type, subtype)

    def verify_api_key(self):
        # 从请求头中获取 API 密钥
        provided_key = self.headers.get('X-API-Key')
        return provided_key == API_KEY

def run(server_class=HTTPServer, handler_class=CustomHandler, port=8000):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f"Server starting on port {port}")
    print(f"Serving files from directory: {STATIC_DIR}")
    print(f"Uploads will be stored in: {UPLOAD_DIR}")
    print(f"Base URL for file access: {BASE_URL}")
    httpd.serve_forever()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    run(port=port)
