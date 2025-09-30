import socket
import os
import time
import threading
import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox, simpledialog
import webbrowser  # 用于打开网页

# 软件介绍和链接设置 - 可在此处修改内容和链接
SOFTWARE_INFO = """
RemoCon远程控制器 v1.0

由辞梦独立开发，基于Python的远程控制工具，支持以下功能：
- 远程命令执行
- 文件传输
- 输入设备锁定/解锁
- 网络连接控制
- 弹窗消息发送
- 系统管理命令预设

声明：
该项目为开源项目，仅供参考学习，使用者行为与开发者无关。
使用前请确保已获得被控设备的授权，
遵守相关法律法规和隐私政策。
"""
AUTHOR_BLOG_URL = "https://cimeng.netlify.app/"  # 作者博客地址
GITHUB_PROJECT_URL = "https://github.com/52Rainbow/RemoCon"  # GitHub项目地址

class RemoteController:
    def __init__(self, root):
        self.root = root
        self.root.title("远程控制器")
        self.root.geometry("900x700")
        self.root.resizable(True, True)
        
        self.client_socket = None
        self.connected = False
        self.target_ip = tk.StringVar(value="127.0.0.1")
        self.target_port = tk.StringVar(value="9999")
        # 与被控端匹配的消息分隔符
        self.MESSAGE_SEPARATOR = "|||__SEP__|||"
        
        # 创建UI
        self.create_ui()
        
    def create_ui(self):
        """创建用户界面"""
        # 连接设置区域
        conn_frame = tk.Frame(self.root, padx=10, pady=5)
        conn_frame.pack(fill=tk.X)
        
        tk.Label(conn_frame, text="目标IP:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        tk.Entry(conn_frame, textvariable=self.target_ip, width=15).grid(row=0, column=1, padx=5, pady=5)
        
        tk.Label(conn_frame, text="端口:").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        tk.Entry(conn_frame, textvariable=self.target_port, width=8).grid(row=0, column=3, padx=5, pady=5)
        
        self.connect_btn = tk.Button(conn_frame, text="连接", command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=4, padx=5, pady=5)
        
        # 关于按钮
        tk.Button(conn_frame, text="关于", command=self.show_about_window).grid(row=0, column=5, padx=5, pady=5)
        
        # 命令输入区域
        cmd_frame = tk.Frame(self.root, padx=10, pady=5)
        cmd_frame.pack(fill=tk.X)
        
        self.cmd_entry = tk.Entry(cmd_frame)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        self.cmd_entry.bind("<Return>", lambda event: self.send_command())
        
        tk.Button(cmd_frame, text="发送命令", command=self.send_command).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(cmd_frame, text="发送文件", command=self.send_file).pack(side=tk.LEFT, padx=5, pady=5)
        
        # 功能按钮区域
        func_frame = tk.Frame(self.root, padx=10, pady=5)
        func_frame.pack(fill=tk.X)
        
        tk.Button(func_frame, text="锁定输入设备", command=lambda: self.send_special_command("__LOCK_INPUT__")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="解锁输入设备", command=lambda: self.send_special_command("__UNLOCK_INPUT__")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="禁用网络", command=lambda: self.send_special_command("__disable_INTERNET__")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="启用网络", command=lambda: self.send_special_command("__enable_INTERNET__")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="发送弹窗", command=self.send_popup).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="退出被控端", command=lambda: self.send_special_command("__EXIT__")).pack(side=tk.LEFT, padx=2, pady=2)
        
        # 预设命令区域
        preset_frame = tk.LabelFrame(self.root, text="预设命令", padx=10, pady=5)
        preset_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 10个预设命令按钮
        presets = [
            ("查看系统信息", "systeminfo"),
            ("查看IP配置", "ipconfig /all"),
            ("查看进程列表", "tasklist"),
            ("查看服务列表", "net start"),
            ("查看目录内容", "dir"),
            ("查看用户列表", "net user"),
            ("关闭计算机", "shutdown /s /t 60"),
            ("重启计算机", "shutdown /r /t 60"),
            ("取消关机", "shutdown /a"),
            ("清除事件日志", "wevtutil cl System")
        ]
        
        # 排列预设命令按钮
        for i, (text, cmd) in enumerate(presets):
            btn = tk.Button(preset_frame, text=text, 
                          command=lambda c=cmd: self.send_preset_command(c))
            btn.grid(row=i//5, column=i%5, padx=5, pady=5, sticky="ew")
        
        # 设置网格权重，使按钮均匀分布
        for i in range(2):
            preset_frame.grid_rowconfigure(i, weight=1)
        for i in range(5):
            preset_frame.grid_columnconfigure(i, weight=1)
        
        # 结果显示区域
        result_frame = tk.Frame(self.root, padx=10, pady=5)
        result_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(result_frame, text="输出结果:").pack(anchor=tk.W)
        self.result_text = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD)
        self.result_text.pack(fill=tk.BOTH, expand=True, pady=5)
        self.result_text.config(state=tk.DISABLED)
    
    def show_about_window(self):
        """显示关于窗口"""
        about_window = tk.Toplevel(self.root)
        about_window.title("关于远程控制器")
        about_window.geometry("500x400")
        about_window.resizable(False, False)
        about_window.transient(self.root)  # 设置为主窗口的子窗口
        about_window.grab_set()  # 模态窗口，阻止对主窗口的操作
        
        # 软件介绍文本
        text_widget = scrolledtext.ScrolledText(about_window, wrap=tk.WORD, padx=10, pady=10)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_widget.insert(tk.END, SOFTWARE_INFO)
        text_widget.config(state=tk.DISABLED, font=("SimHei", 10))
        
        # 按钮区域
        btn_frame = tk.Frame(about_window, pady=10)
        btn_frame.pack(fill=tk.X, padx=10)
        
        # 打开博客按钮
        tk.Button(
            btn_frame, 
            text="访问作者博客", 
            command=lambda: webbrowser.open(AUTHOR_BLOG_URL)
        ).pack(side=tk.LEFT, padx=20, expand=True)
        
        # 打开GitHub按钮
        tk.Button(
            btn_frame, 
            text="查看GitHub项目", 
            command=lambda: webbrowser.open(GITHUB_PROJECT_URL)
        ).pack(side=tk.RIGHT, padx=20, expand=True)
        
        # 关闭按钮
        tk.Button(about_window, text="关闭", command=about_window.destroy).pack(pady=10)
        
    def toggle_connection(self):
        """切换连接状态（连接/断开）"""
        if not self.connected:
            self.connect_to_server()
        else:
            self.disconnect()
    
    def connect_to_server(self):
        """连接到被控端服务器"""
        try:
            ip = self.target_ip.get()
            port = int(self.target_port.get())
            
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((ip, port))
            
            self.connected = True
            self.connect_btn.config(text="断开连接")
            self.append_result(f"已成功连接到 {ip}:{port}")
            
            # 启动接收线程
            self.receive_thread = threading.Thread(target=self.receive_data, daemon=True)
            self.receive_thread.start()
            
        except Exception as e:
            self.append_result(f"连接失败: {str(e)}")
            self.client_socket = None
    
    def disconnect(self):
        """断开与被控端的连接"""
        if self.connected and self.client_socket:
            try:
                self.client_socket.close()
            except Exception as e:
                self.append_result(f"断开连接时出错: {str(e)}")
            
            self.connected = False
            self.connect_btn.config(text="连接")
            self.append_result("已断开连接")
            self.client_socket = None
    
    def receive_data(self):
        """接收被控端返回的数据"""
        while self.connected and self.client_socket:
            try:
                data = self.client_socket.recv(4096).decode('utf-8')
                if not data:
                    self.append_result("连接已被远程关闭")
                    self.disconnect()
                    break
                self.append_result(f"收到: {data}")
            except Exception as e:
                if self.connected:  # 只有在仍然连接的情况下才显示错误
                    self.append_result(f"接收数据出错: {str(e)}")
                break
    
    def send_command(self):
        """发送命令到被控端"""
        if not self.connected or not self.client_socket:
            messagebox.showwarning("警告", "请先建立连接")
            return
        
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        
        try:
            self.client_socket.sendall(cmd.encode('utf-8'))
            self.append_result(f"已发送命令: {cmd}")
            self.cmd_entry.delete(0, tk.END)
        except Exception as e:
            self.append_result(f"发送命令失败: {str(e)}")
            self.disconnect()
    
    def send_preset_command(self, cmd):
        """发送预设命令"""
        if not self.connected or not self.client_socket:
            messagebox.showwarning("警告", "请先建立连接")
            return
            
        # 在输入框中显示预设命令，方便用户查看和修改
        self.cmd_entry.delete(0, tk.END)
        self.cmd_entry.insert(0, cmd)
        
        try:
            self.client_socket.sendall(cmd.encode('utf-8'))
            self.append_result(f"已发送预设命令: {cmd}")
        except Exception as e:
            self.append_result(f"发送预设命令失败: {str(e)}")
            self.disconnect()
    
    def send_special_command(self, command):
        """发送特殊控制命令"""
        if not self.connected or not self.client_socket:
            messagebox.showwarning("警告", "请先建立连接")
            return
        
        try:
            self.client_socket.sendall(command.encode('utf-8'))
            self.append_result(f"已发送特殊命令: {command}")
        except Exception as e:
            self.append_result(f"发送命令失败: {str(e)}")
            self.disconnect()
    
    def send_popup(self):
        """发送弹窗消息（修复版，与被控端匹配）"""
        if not self.connected or not self.client_socket:
            messagebox.showwarning("警告", "请先建立连接")
            return
        
        msg = simpledialog.askstring("输入消息", "请输入要显示的弹窗消息:")
        if msg is not None:  # 允许空消息，但要处理
            try:
                # 使用特殊分隔符，避免与消息内容中的|冲突
                command = f"__POPUP_MESSAGE__{self.MESSAGE_SEPARATOR}{msg}"
                self.client_socket.sendall(command.encode('utf-8'))
                
                # 等待确认消息
                timeout = 5
                start_time = time.time()
                self.client_socket.settimeout(1)
                
                while time.time() - start_time < timeout:
                    try:
                        response = self.client_socket.recv(1024).decode('utf-8')
                        if response:
                            self.append_result(f"弹窗响应: {response}")
                            return
                    except socket.timeout:
                        continue
                
                self.append_result(f"弹窗消息已发送，但未收到确认")
                
            except Exception as e:
                self.append_result(f"发送弹窗消息失败: {str(e)}")
                self.disconnect()
            finally:
                self.client_socket.settimeout(None)
    
    def send_file(self):
        """发送文件到被控端"""
        if not self.connected or not self.client_socket:
            messagebox.showwarning("警告", "请先建立连接")
            return
        
        file_path = filedialog.askopenfilename(title="选择要发送的文件")
        if not file_path:
            return
        
        try:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            # 发送文件信息
            command = f"__SEND_FILE__|{file_name}|{file_size}"
            self.client_socket.sendall(command.encode('utf-8'))
            
            # 等待被控端准备好
            time.sleep(1)
            
            # 发送文件内容
            with open(file_path, 'rb') as f:
                bytes_sent = 0
                while bytes_sent < file_size:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    self.client_socket.sendall(chunk)
                    bytes_sent += len(chunk)
            
            self.append_result(f"文件 {file_name} 发送完成，大小: {file_size} 字节")
            
        except Exception as e:
            self.append_result(f"发送文件失败: {str(e)}")
            self.disconnect()
    
    def append_result(self, text):
        """在结果区域添加文本"""
        self.result_text.config(state=tk.NORMAL)
        self.result_text.insert(tk.END, text + "\n")
        self.result_text.see(tk.END)  # 滚动到最后
        self.result_text.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    app = RemoteController(root)
    root.mainloop()
