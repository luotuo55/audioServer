import requests
import os

def upload_audio(file_path, server_url, api_key):
    if not os.path.exists(file_path):
        print(f"错误：文件 {file_path} 不存在")
        return

    try:
        with open(file_path, 'rb') as audio_file:
            # 根据文件扩展名设置正确的 Content-Type
            file_extension = os.path.splitext(file_path)[1].lower()
            if file_extension == '.wav':
                content_type = 'audio/wav'
            elif file_extension == '.mp3':
                content_type = 'audio/mpeg'
            else:
                content_type = 'audio/mpeg'  # 默认使用 audio/mpeg
            
            headers = {
                'Content-Type': content_type,
                'X-API-Key': api_key  # 使用 X-API-Key 头部传递 API 密钥
            }
            response = requests.post(f"{server_url}/api/upload", data=audio_file, headers=headers)
        
        if response.status_code == 200:
            print("文件上传成功")
            print("服务器响应:", response.json())
        elif response.status_code == 401:
            print("上传失败：无效的 API 密钥")
        else:
            print(f"上传失败，状态码: {response.status_code}")
            print("服务器响应:", response.text)
    except requests.RequestException as e:
        print(f"上传过程中发生错误: {e}")

if __name__ == "__main__":
    server_url = "http://www.52ai.fun"
    audio_file_path = os.path.join(os.path.dirname(__file__), "2.wav")
    api_key = "1F1vmARoSjXRTDvywh9XtbnR8vd74AfffF0t0jn3qhM"  # 替换为服务器生成的实际 API 密钥arPmwKIS3vDRn8kLyesSQw6bZGZVkPbHDEAnH9avi7w
    
    upload_audio(audio_file_path, server_url, api_key)
