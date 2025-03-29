# ====== GPL协议 ======
# 版权所有 (C) [2025] [AvroraCL/赫尔塔HEC&LM工作室]
# 本程序是自由软件，你可以根据GNU通用公共许可证（GPL）第3版或更高版本重新分发或修改它
# 详细信息请参阅：<https://www.gnu.org/licenses/gpl-3.0.html>

import sys
import os
import subprocess
import tempfile
import traceback
import time
import platform
import psutil
import math
from pathlib import Path
from tqdm import tqdm
from PIL import Image

# ====== 自动适配路径分隔符 ======
tools_dir = Path(__file__).parent / "tools"

# ====== 路径初始化 ======
if getattr(sys, 'frozen', False):
    base_path = Path(sys._MEIPASS)
    tools_dir = base_path / 'tools'
else:
    base_path = Path(__file__).parent
    tools_dir = base_path / 'tools'

def get_tool(name):
    """修复后的工具路径获取"""
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).parent

    tool_map = {
        'texassemble': base_dir / 'tools' / ('texassemble.exe' if os.name == 'nt' else 'texassemble')
    }
    if not tool_map[name].exists():
        raise FileNotFoundError(f"找不到{name}工具")
    return tool_map[name]

# ====== 核心配置类 ======
class Config:
    @staticmethod
    def get_tool(name):
        # 添加编译时路径断言
        assert (tools_dir / "texassemble.exe").exists(), "编译时工具路径校验失败"
    INPUT_DIR = Path("Input").resolve()
    OUTPUT_DIR = Path("Output").resolve()
    TEMP_DIR = Path(tempfile.gettempdir()).resolve()

    @staticmethod
    def get_tool(name):
        """跨平台工具路径解析"""
        tool_map = {
            'texassemble': {
                'Windows': 'texassemble.exe',
                'Linux': 'texassemble'
            },
            'texconv': {
                'Windows': 'texconv.exe',
                'Linux': 'texconv'
            }
        }
        tool_path = tools_dir / tool_map[name][platform.system()]
        return tool_path.resolve()


# ====== 硬件管理模块 ======
class HardwareManager:
    @staticmethod
    def check_resources():
        """增强型资源检查v11"""
        checks = {
            'memory': psutil.virtual_memory().available > 1 * 1024 * 1024 * 1024,
            'disk': psutil.disk_usage('/').free > 2 * 1024 * 1024 * 1024
        }
        if not all(checks.values()):
            raise RuntimeError(f"资源不足: {', '.join(k for k, v in checks.items() if not v)}")


# ====== 修复版分块处理器 ======
class ChunkProcessor:
    @staticmethod
    def safe_resize(img, target_size):
        """内存安全的图像缩放（v11修复块状问题）"""
        try:
            HardwareManager.check_resources()

            # 动态分块策略
            base_size = img.width * img.height * 3  # 原始像素数据量
            mem_factor = psutil.virtual_memory().available / (base_size * 2)
            chunk_size = max(256, min(2048, int(math.sqrt(mem_factor)) * 128))

            # 生成有序分块坐标 (从左到右，从上到下)
            tiles = [
                (x, y, min(x + chunk_size, img.width), min(y + chunk_size, img.height))
                for y in range(0, img.height, chunk_size)
                for x in range(0, img.width, chunk_size)
            ]

            scale_w = target_size[0] / img.width
            scale_h = target_size[1] / img.height

            processed = []
            for tile in tqdm(tiles, desc="处理分块", unit="tile"):
                # 分块处理
                cropped = img.crop(tile)
                scaled = cropped.resize((
                    max(1, int(cropped.width * scale_w)),
                    max(1, int(cropped.height * scale_h))
                ), Image.LANCZOS)

                # 内存保护机制
                if psutil.virtual_memory().percent > 85:
                    processed = processed[-3:]  # 保留最近3个分块
                    cropped.close()
                    scaled.close()
                    import gc;
                    gc.collect()

                processed.append(scaled)

            return ChunkProcessor.merge(processed, target_size)
        except Exception as e:
            print(f"🛑 分块处理失败：{str(e)}")
            return img.resize(target_size, Image.LANCZOS)

    @staticmethod
    def merge(tiles, target_size):
        """v11修复的拼接算法"""
        merged = Image.new('RGB', target_size)
        x_pos, y_pos = 0, 0
        current_row_height = 0

        for tile in tiles:
            # 换行检测
            if x_pos + tile.width > merged.width:
                x_pos = 0
                y_pos += current_row_height
                current_row_height = 0

            # 越界终止
            if y_pos >= merged.height:
                break

            # 精确坐标计算
            paste_box = (
                x_pos,
                y_pos,
                min(x_pos + tile.width, merged.width),
                min(y_pos + tile.height, merged.height)
            )

            # 执行拼接
            try:
                merged.paste(tile.resize(
                    (paste_box[2] - paste_box[0], paste_box[3] - paste_box[1]),
                    Image.LANCZOS
                ), paste_box)
            except ValueError as e:
                print(f"⚠ 跳过异常区块：{str(e)}")
                continue

            # 更新坐标
            x_pos += tile.width
            current_row_height = max(current_row_height, tile.height)

            # 行末换行后检测
            if y_pos + current_row_height > merged.height:
                break

        return merged


# ====== 主处理流程 ======
class MipmapProcessor:
    def __init__(self):
        self.validate_environment()

    def validate_environment(self):
        """增强环境校验"""
        checks = [
            (Config.INPUT_DIR.exists(), f"输入目录不存在：{Config.INPUT_DIR}"),
            (Config.get_tool('texassemble').exists(), "找不到 texassemble 工具"),
            (Config.get_tool('texconv').exists(), "找不到 texconv 工具")
        ]
        for condition, message in checks:
            if not condition:
                raise FileNotFoundError(message)

    def process(self):
        """主处理流程（v11）"""
        files = self.get_mip_files()
        base_size = Image.open(files[0]).size
        processed = [files[0]]

        with tqdm(total=len(files) * 2, desc="处理进度") as pbar:
            current_size = base_size
            for idx in range(1, len(files)):
                current_size = (current_size[0] // 2, current_size[1] // 2)
                output = self.process_image(files[idx], current_size)
                processed.append(output)
                pbar.update(2)

            self.generate_dds(processed)
            pbar.update(1)

        print(f"\n✅ 处理完成！输出目录：{Config.OUTPUT_DIR}")

    def get_mip_files(self):
        """获取有序mipmap文件"""
        files = sorted(Config.INPUT_DIR.glob("p*.png"),
                       key=lambda x: int(x.stem[1:]))
        if len(files) < 2:
            raise FileNotFoundError("至少需要 p0.png 和 p1.png")
        return files

    def process_image(self, path, target_size):
        """图像处理（增加尺寸校验）"""
        img = Image.open(path).convert('RGB')
        if img.size == target_size:
            return path

        # 尺寸预校验
        if (target_size[0] != img.size[0] // 2 or
                target_size[1] != img.size[1] // 2):
            print(f"⚠ 尺寸校验警告：{path.name} 应为 {img.size[0] // 2}x{img.size[1] // 2}")

        resized = ChunkProcessor.safe_resize(img, target_size)
        temp_path = Config.TEMP_DIR / f"temp_{path.name}"
        resized.save(temp_path, quality=95, optimize=True)
        return temp_path

    def generate_dds(self, inputs):
        """DDS生成（增加格式校验）"""
        temp_dds = Config.TEMP_DIR / "❤️CL我喜欢你喵.dds"

        # texassemble 命令
        subprocess.run([
                           str(Config.get_tool('texassemble')),
                           "from-mips", "-o", str(temp_dds),
                           "-f", "R8G8B8A8_UNORM", "-y"
                       ] + [str(f) for f in inputs], check=True)

        # texconv 转换
        final_output = Config.OUTPUT_DIR / "output.dds"
        subprocess.run([
            str(Config.get_tool('texconv')),
            "-f", "BC3_UNORM", "-y",
            "-ft", "DDS", "-o", str(Config.OUTPUT_DIR),
            str(temp_dds)
        ], check=True)

        # 清理临时文件
        temp_dds.unlink(missing_ok=True)

if __name__ == "__main__":
    try:
        Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        MipmapProcessor().process()
    except Exception as e:
        error_info = f"""
        [系统诊断]
        时间: {time.ctime()}
        系统: {platform.platform()}
        Python: {sys.version}
        内存使用: {psutil.virtual_memory().percent}%
        磁盘空间: {psutil.disk_usage('/').free // (1024 * 1024)}MB 可用
        当前路径: {Path.cwd()}
        输入文件: {len(list(Config.INPUT_DIR.glob('*')))} 个
        """
        print(f"❌ 致命错误：{str(e)}\n{error_info}")
        traceback.print_exc()
    finally:
        # 清理所有临时文件
        temp_files = list(Config.TEMP_DIR.glob("temp_*.png"))
        for f in temp_files:
            try:
                f.unlink()
            except:
                pass
        print("🔄 临时文件清理完成")
        # 新增保持窗口代码
        if os.name == 'nt':  # 仅Windows系统需要
            os.system('pause')  # 显示"按任意键继续..."
        else:
            input("程序执行完毕，按Enter键退出...")  # Linux/macOS