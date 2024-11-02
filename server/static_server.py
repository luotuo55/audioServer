from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import json
from datetime import datetime
import cgi
import traceback
import re
from urllib.parse import parse_qs
import threading
import time
from datetime import datetime, timedelta

# 基础配置
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'voice')

# 版本信息
VERSION = "1.6"
VERSION_INFO = {
    'version': VERSION,
    'release_date': '2024-02-11',
    'features': [
        '支持音频文件上传和播放',
        '域名白名单管理',
        '文件自动清理',
        '操作日志记录',
        '管理后台功能'
    ]
}

def print_version_info():
    """打印版本信息"""
    print("\n=== 音频文件服务器 V{} ===".format(VERSION))
    print(f"发布日期: {VERSION_INFO['release_date']}")
    print("\n主要功能:")
    for feature in VERSION_INFO['features']:
        print(f"- {feature}")
    print("="*30 + "\n")

class ConfigManager:
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self.load_config()

    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.allowed_origins = set(config.get('allowed_origins', []))
                    self.domain_patterns = [re.compile(pattern) 
                                         for pattern in config.get('domain_patterns', [])]
                    self.admin_key = config.get('admin_key', 'default_admin_key')
                print(f"已加载配置: {len(self.allowed_origins)} 个域名, "
                      f"{len(self.domain_patterns)} 个模式")
            else:
                self.allowed_origins = set()
                self.domain_patterns = []
                self.admin_key = 'default_admin_key'
                self.save_config()
        except Exception as e:
            print(f"加载配置失败: {e}")
            self.allowed_origins = set()
            self.domain_patterns = []
            self.admin_key = 'default_admin_key'

    def save_config(self):
        """保存配置"""
        try:
            config = {
                'allowed_origins': list(self.allowed_origins),
                'domain_patterns': [pattern.pattern for pattern in self.domain_patterns],
                'admin_key': self.admin_key
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            print("配置已保存")
        except Exception as e:
            print(f"保存配置失败: {e}")

    def is_origin_allowed(self, origin):
        """检查来源是否允许"""
        if not origin:
            return False
            
        # 检查精确匹配
        if origin in self.allowed_origins:
            return True
            
        # 检查模式匹配
        return any(pattern.match(origin) for pattern in self.domain_patterns)

    def verify_admin_key(self, key):
        """验证管理员密钥"""
        return key == self.admin_key

    def add_origin(self, origin, is_pattern):
        """添加域名"""
        if is_pattern:
            pattern = re.compile(origin)
            self.domain_patterns.append(pattern)
        else:
            self.allowed_origins.add(origin)
        self.save_config()
        return True

    def remove_origin(self, origin, is_pattern):
        """删除域名"""
        if is_pattern:
            pattern = re.compile(origin)
            if pattern in self.domain_patterns:
                self.domain_patterns.remove(pattern)
            else:
                return False
        else:
            if origin in self.allowed_origins:
                self.allowed_origins.remove(origin)
            else:
                return False
        self.save_config()
        return True

class FileCleanupThread(threading.Thread):
    """文件清理线程"""
    def __init__(self, upload_dir, interval=300):  # 默认每5分钟检查一次
        super().__init__()
        self.upload_dir = upload_dir
        self.interval = interval
        self.daemon = True  # 设置为守护线程，主程序退出时自动结束
        
    def run(self):
        while True:
            try:
                print("\n=== 开始清理过期文件 ===")
                self.cleanup_files()
                time.sleep(self.interval)
            except Exception as e:
                print(f"清理文件时出错: {e}")
                print(traceback.format_exc())
                time.sleep(60)  # 出错后等待1分钟再试
    
    def cleanup_files(self):
        """清理过期文件"""
        try:
            now = datetime.now()
            expiry_time = now - timedelta(hours=1)
            cleaned_count = 0
            cleaned_size = 0
            
            for filename in os.listdir(self.upload_dir):
                file_path = os.path.join(self.upload_dir, filename)
                file_time = datetime.fromtimestamp(os.path.getctime(file_path))
                
                if file_time < expiry_time:
                    file_size = os.path.getsize(file_path)
                    os.remove(file_path)
                    cleaned_count += 1
                    cleaned_size += file_size
                    
                    # 记录自动清理日志
                    self.logger.log('auto_delete', {
                        'filename': filename,
                        'size': file_size,
                        'age': str(now - file_time),
                        'reason': 'expired'
                    })
            
            if cleaned_count > 0:
                self.logger.log('cleanup_summary', {
                    'cleaned_files': cleaned_count,
                    'cleaned_size': cleaned_size,
                    'expiry_hours': 1
                })
                
        except Exception as e:
            print(f"清理文件时出错: {e}")
            print(traceback.format_exc())
            self.logger.log('cleanup_error', {
                'error': str(e)
            })

def formatSize(size):
    """格式化件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

class CustomHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, config_manager=None, logger=None, **kwargs):
        self.config_manager = config_manager
        self.logger = logger
        super().__init__(*args, **kwargs)
        print(f"Handler初始化 - logger: {self.logger is not None}")

    def handle_file_upload(self):
        """处理文件上传"""
        try:
            print("\n=== 处理文件上传 ===")
            print(f"Logger状态: {self.logger is not None}")
            
            if not self.verify_origin():
                error_msg = "Origin not allowed"
                print(f"上传失败: {error_msg}")
                if self.logger:
                    self.logger.log('upload_error', {
                        'error': error_msg,
                        'origin': self.headers.get('Origin', 'unknown'),
                        'ip': self.client_address[0]
                    })
                self.send_error(403, error_msg)
                return
                
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            boundary = self.headers['Content-Type'].split('=')[1].encode()
            parts = post_data.split(boundary)
            
            for part in parts:
                if b'filename=' in part:
                    filename = part.split(b'filename=')[1].split(b'\r\n')[0].strip(b'"').decode()
                    file_start = part.index(b'\r\n\r\n') + 4
                    file_content = part[file_start:-2]
                    
                    # 生成安全的文件名
                    safe_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
                    filepath = os.path.join(UPLOAD_DIR, safe_filename)
                    
                    print(f"保存文件: {filepath}")
                    with open(filepath, 'wb') as f:
                        f.write(file_content)
                    
                    # 获取服务器地址
                    host = self.headers.get('Host', 'localhost:8000')
                    if not host.startswith(('http://', 'https://')):
                        host = f"http://{host}"
                    
                    # 生成文件URL
                    file_url = f"{host}/voice/{safe_filename}"
                    
                    # 记录到上传记录文件
                    upload_record = {
                        'filename': safe_filename,
                        'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'size': len(file_content),
                        'url': file_url
                    }
                    
                    print("记录上传信息到 upload_records.txt")
                    with open('upload_records.txt', 'a', encoding='utf-8') as f:
                        f.write(json.dumps(upload_record, ensure_ascii=False) + '\n')
                    
                    # 记录到系统日志
                    if self.logger:
                        print("记录上传日志到 server_logs.txt")
                        log_success = self.logger.log('upload', {
                            'filename': safe_filename,
                            'original_filename': filename,
                            'size': len(file_content),
                            'url': file_url,
                            'ip': self.client_address[0],
                            'user_agent': self.headers.get('User-Agent', 'unknown'),
                            'origin': self.headers.get('Origin', 'unknown')
                        })
                        print(f"日志记录状态: {'成功' if log_success else '失败'}")
                    else:
                        print("警告: logger未初始化")
                    
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
                            'file_url': file_url,
                            'upload_time': upload_record['datetime'],
                            'expires_in': '1小时'
                        }
                    }
                    
                    response_json = json.dumps(response, ensure_ascii=False)
                    print(f"发送响应: {response_json}")
                    self.wfile.write(response_json.encode('utf-8'))
                    return
                    
            raise Exception('No file found in upload')
            
        except Exception as e:
            error_msg = f"上传错误: {str(e)}"
            print(error_msg)
            print(traceback.format_exc())
            # 记录错误日志
            if self.logger:
                self.logger.log('upload_error', {
                    'error': str(e),
                    'ip': self.client_address[0],
                    'user_agent': self.headers.get('User-Agent', 'unknown')
                })
            self.send_error(500, str(e))

    def do_POST(self):
        """处理POST请求"""
        print(f"\n=== 处理POST请求 ===")
        print(f"请求路径: {self.path}")
        
        if self.path == '/api/upload':
            if not self.verify_origin():
                self.send_error(403, "Origin not allowed")
                return
            self.handle_file_upload()
        elif self.path == '/api/admin/domains':
            self.handle_domain_management()
        else:
            self.send_error(404, "API not found")

    def verify_admin(self):
        """验管理员权限"""
        admin_key = self.headers.get('X-Admin-Key')
        if not self.config_manager.verify_admin_key(admin_key):
            self.send_error(401, "Invalid admin key")
            return False
        return True

    def verify_origin(self):
        """验证请求来源"""
        origin = self.headers.get('Origin')
        if not origin:
            referer = self.headers.get('Referer')
            if referer:
                origin = '/'.join(referer.split('/')[:3])
        return self.config_manager.is_origin_allowed(origin)

    def do_GET(self):
        """处理GET请求"""
        print(f"\n=== 处理GET请求 ===")
        print(f"请求路径: {self.path}")
        
        try:
            # 处理日志请求
            if self.path.startswith('/api/admin/logs'):
                self.handle_logs()
                return
                
            # 处理音频文件请求
            if self.path.startswith('/voice/'):
                self.handle_audio_file()
                return

            # 处理特殊路由
            if self.path == '/admin' or self.path == '/admin/':
                self.path = '/admin.html'
            elif self.path == '/':
                self.path = '/index.html'

            # 处理管理员API
            if self.path.startswith('/api/admin/uploads'):
                self.handle_admin_uploads()
                return

            # 获取文件路径
            if self.path.startswith('/'):
                file_path = os.path.join(STATIC_DIR, self.path[1:])
            else:
                file_path = os.path.join(STATIC_DIR, self.path)

            print(f"尝试访问文件: {file_path}")

            # 检查文件是否存在
            if os.path.exists(file_path) and os.path.isfile(file_path):
                with open(file_path, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                content_type = self.guess_type(file_path)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', len(content))
                self.end_headers()
                self.wfile.write(content)
                print(f"文件发送成功: {file_path}")
            else:
                print(f"文件不存在: {file_path}")
                self.send_error(404, 'File not found')
        except Exception as e:
            print(f"Error: {e}")
            print(traceback.format_exc())
            self.send_error(500, str(e))

    def guess_type(self, path):
        """获取文件的MIME类型"""
        ext = os.path.splitext(path)[1].lower()
        return {
            '.html': 'text/html; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav'
        }.get(ext, 'application/octet-stream')

    def handle_admin_uploads(self):
        """处理管理员上传列表请求"""
        try:
            # 验证管理员密钥
            admin_key = self.headers.get('X-Admin-Key')
            if not self.config_manager.verify_admin_key(admin_key):
                self.send_error(401, 'Invalid admin key')
                return

            # 读取上传记录
            records = []
            if os.path.exists('upload_records.txt'):
                with open('upload_records.txt', 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            record = json.loads(line.strip())
                            # 检查文件是否仍然存在
                            file_path = os.path.join(UPLOAD_DIR, record['filename'])
                            if os.path.exists(file_path):
                                record['exists'] = True
                                record['size'] = os.path.getsize(file_path)
                            else:
                                record['exists'] = False
                            records.append(record)
                        except Exception as e:
                            print(f"解析记录失败: {e}")
                            continue

            # 按时间倒序排序
            records.sort(key=lambda x: x.get('datetime', ''), reverse=True)

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
            
            response_json = json.dumps(response, ensure_ascii=False)
            print(f"发送上传记录: {len(records)} 条")
            self.wfile.write(response_json.encode('utf-8'))
            
        except Exception as e:
            print(f"处理管理员上传列表请求失败: {e}")
            print(traceback.format_exc())
            self.send_error(500, str(e))

    def handle_audio_file(self):
        """处理音频文件请求"""
        try:
            # 获取文件名
            file_name = os.path.basename(self.path[7:])  # 移除 '/voice/' 前缀
            file_path = os.path.join(UPLOAD_DIR, file_name)
            
            print(f"请求音频文件: {file_path}")
            
            if os.path.exists(file_path) and os.path.isfile(file_path):
                # 允许所有域名访问
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

    def handle_delete_file(self):
        """处理文件删除请求"""
        try:
            # 验证管理员密钥
            admin_key = self.headers.get('X-Admin-Key')
            if not self.config_manager.verify_admin_key(admin_key):
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

    def handle_domain_management(self):
        """处理域名管理请求"""
        try:
            # 验证管理员密钥
            admin_key = self.headers.get('X-Admin-Key')
            if not self.config_manager.verify_admin_key(admin_key):
                self.send_error(401, 'Invalid admin key')
                return

            # 获取请求数据
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            action = data.get('action')
            
            # 处理列表请求
            if action == 'list':
                response = {
                    'allowed_origins': list(self.config_manager.allowed_origins),
                    'domain_patterns': [p.pattern for p in self.config_manager.domain_patterns]
                }
            # 处理添加请求
            elif action == 'add':
                origin = data.get('origin')
                is_pattern = data.get('is_pattern', False)
                success = self.config_manager.add_origin(origin, is_pattern)
                response = {
                    'success': success,
                    'allowed_origins': list(self.config_manager.allowed_origins),
                    'domain_patterns': [p.pattern for p in self.config_manager.domain_patterns]
                }
            # 处理删除请求
            elif action == 'remove':
                origin = data.get('origin')
                is_pattern = data.get('is_pattern', False)
                success = self.config_manager.remove_origin(origin, is_pattern)
                response = {
                    'success': success,
                    'allowed_origins': list(self.config_manager.allowed_origins),
                    'domain_patterns': [p.pattern for p in self.config_manager.domain_patterns]
                }
            else:
                self.send_error(400, 'Invalid action')
                return

            # 发送响应
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))

        except Exception as e:
            print(f"处理域名管理请求失败: {e}")
            print(traceback.format_exc())
            self.send_error(500, str(e))

    def do_DELETE(self):
        """处理DELETE请求"""
        print(f"\n=== 处理DELETE请求 ===")
        print(f"请求路径: {self.path}")
        
        try:
            if self.path.startswith('/api/admin/delete/'):
                # 验证管理员密钥
                admin_key = self.headers.get('X-Admin-Key')
                if not self.config_manager.verify_admin_key(admin_key):
                    self.logger.log('delete_error', {
                        'error': 'Invalid admin key',
                        'ip': self.client_address[0]
                    })
                    self.send_error(401, 'Invalid admin key')
                    return

                # 获取文件名
                file_name = os.path.basename(self.path)
                file_path = os.path.join(UPLOAD_DIR, file_name)
                
                if os.path.exists(file_path):
                    # 记录删除前的文件信息
                    file_size = os.path.getsize(file_path)
                    
                    # 删除文件
                    os.remove(file_path)
                    
                    # 记录删除日志
                    self.logger.log('delete', {
                        'filename': file_name,
                        'size': file_size,
                        'ip': self.client_address[0],
                        'admin_key': admin_key[:3] + '***',  # 部分隐藏管理员密钥
                        'reason': 'manual_delete'
                    })
                    
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
                else:
                    self.logger.log('delete_error', {
                        'error': 'File not found',
                        'filename': file_name,
                        'ip': self.client_address[0]
                    })
                    self.send_error(404, "File not found")
            else:
                self.send_error(404, "API not found")
        except Exception as e:
            print(f"删除文件失败: {e}")
            print(traceback.format_exc())
            # 记录错误日志
            self.logger.log('delete_error', {
                'error': str(e),
                'ip': self.client_address[0]
            })
            self.send_error(500, str(e))

    def do_OPTIONS(self):
        """处理OPTIONS请求"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Admin-Key')
        self.end_headers()

    def handle_logs(self):
        """处理日志请求"""
        try:
            # 验证管理员密钥
            admin_key = self.headers.get('X-Admin-Key')
            if not self.config_manager.verify_admin_key(admin_key):
                self.send_error(401, 'Invalid admin key')
                return

            # 解析查询参数
            from urllib.parse import urlparse, parse_qs
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)
            
            # 获取过滤参数
            start_date = query_params.get('start_date', [None])[0]
            end_date = query_params.get('end_date', [None])[0]
            action_type = query_params.get('action_type', [None])[0]

            # 获取日志
            logs = self.logger.get_logs(start_date, end_date, action_type)

            # 发送响应
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response = {
                'code': 200,
                'message': 'success',
                'data': logs
            }
            
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
            
        except Exception as e:
            print(f"处理日志请求失败: {e}")
            print(traceback.format_exc())
            self.send_error(500, str(e))

    def log_action(self, action, details):
        """记录操作日志"""
        try:
            # 添加IP地址和时间戳
            details['ip'] = self.client_address[0]
            details['user_agent'] = self.headers.get('User-Agent', 'unknown')
            
            self.logger.log(action, details)
        except Exception as e:
            print(f"记录日志失败: {e}")
            print(traceback.format_exc())

class Logger:
    def __init__(self, log_dir='logs'):
        """初始化日志系统"""
        # 确保日志目录存在
        self.log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), log_dir)
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 设置日志文件路径
        self.log_file = os.path.join(self.log_dir, 'server_logs.txt')
        
        print(f"\n=== 初始化日志系统 ===")
        print(f"日志目录: {self.log_dir}")
        print(f"日志文件: {self.log_file}")
        
        # 创建或检查日志文件
        try:
            if not os.path.exists(self.log_file):
                # 创建新文件并写入初始记录
                self._write_init_log()
            else:
                # 验证文件内容
                self._validate_log_file()
        except Exception as e:
            print(f"初始化日志文件时出错: {e}")
            print(traceback.format_exc())
            # 如果有错误，重新创建文件
            self._write_init_log()

    def _write_init_log(self):
        """写入初始化日志"""
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                init_log = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'action': 'system',
                    'details': {
                        'event': 'log_init',
                        'version': VERSION,
                        'message': '日志系统初始化'
                    }
                }
                f.write(json.dumps(init_log, ensure_ascii=False) + '\n')
            print("创建新的日志文件并写入初始记录")
        except Exception as e:
            print(f"写入初始日志失败: {e}")
            print(traceback.format_exc())

    def _validate_log_file(self):
        """验证日志文件内容"""
        try:
            valid_lines = []
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                for line in lines:
                    try:
                        # 验证每行是否为有效的JSON
                        json.loads(line.strip())
                        valid_lines.append(line)
                    except:
                        print(f"发现无效日志行: {line.strip()}")
                        continue
            
            # 如果有无效行，重写文件只保留有效记录
            if len(valid_lines) != len(lines):
                print(f"清理无效日志记录: 原有 {len(lines)} 行，有效 {len(valid_lines)} 行")
                with open(self.log_file, 'w', encoding='utf-8') as f:
                    for line in valid_lines:
                        f.write(line)
            
            print(f"当前日志文件包含 {len(valid_lines)} 条有效记录")
        except Exception as e:
            print(f"验证日志文件失败: {e}")
            print(traceback.format_exc())
            # 如果验证失败，重新创建文件
            self._write_init_log()

    def log(self, action, details):
        """记录日志"""
        try:
            log_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'action': action,
                'details': details
            }
            
            # 验证日志条目是否为有效的JSON
            json.dumps(log_entry, ensure_ascii=False)
            
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            
            print(f"日志记录成功: {action}")
            return True
        except Exception as e:
            print(f"记录日志失败: {e}")
            print(traceback.format_exc())
            return False

    def get_logs(self, start_date=None, end_date=None, action_type=None):
        """获取日志记录"""
        try:
            print(f"\n=== 开始查询日志 ===")
            print(f"查询参数 - 开始日期: {start_date}, 结束日期: {end_date}, 操作类型: {action_type}")
            
            logs = []
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:  # 跳过空行
                            continue
                        try:
                            log = json.loads(line)
                            if self._filter_log(log, start_date, end_date, action_type):
                                logs.append(log)
                        except json.JSONDecodeError as e:
                            print(f"解析第 {line_num} 行日志失败: {e}")
                            print(f"问题行内容: {line}")
                            continue
            
            print(f"筛选得到 {len(logs)} 条日志记录")
            return logs
        except Exception as e:
            print(f"读取日志失败: {e}")
            print(traceback.format_exc())
            return []

    def _filter_log(self, log, start_date, end_date, action_type):
        """过滤日志记录"""
        try:
            log_timestamp = datetime.strptime(log['timestamp'], '%Y-%m-%d %H:%M:%S')
            
            if start_date:
                start = datetime.strptime(start_date, '%Y-%m-%d')
                if log_timestamp.date() < start.date():
                    return False
            
            if end_date:
                end = datetime.strptime(end_date, '%Y-%m-%d')
                if log_timestamp.date() > end.date():
                    return False
            
            if action_type and log['action'] != action_type:
                return False
            
            return True
        except Exception as e:
            print(f"过滤日志时出错: {e}")
            return False

def run(port=8000):
    """启动服务器"""
    print_version_info()
    
    # 创建必要的目录
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # 确保记录文件存在
    if not os.path.exists('upload_records.txt'):
        print("创建 upload_records.txt")
        with open('upload_records.txt', 'w', encoding='utf-8') as f:
            pass
    
    # 创建日志记录器
    logger = Logger()
    print(f"Logger初始化完成: {logger is not None}")
    
    # 创建服务器
    config_manager = ConfigManager()
    
    class HandlerClass(CustomHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, config_manager=config_manager, logger=logger, **kwargs)
    
    server_address = ('', port)
    httpd = HTTPServer(server_address, HandlerClass)
    
    print(f"\n=== 服务器配置 ===")
    print(f"端口: {port}")
    print(f"静态目录: {STATIC_DIR}")
    print(f"上传目录: {UPLOAD_DIR}")
    print(f"日志文件: {logger.log_file}")
    print(f"管理密钥: {config_manager.admin_key}")
    print("="*30 + "\n")
    
    # 启动文件清理线程
    cleanup_thread = FileCleanupThread(UPLOAD_DIR, logger)
    cleanup_thread.start()
    
    httpd.serve_forever()

if __name__ == '__main__':
    run()
