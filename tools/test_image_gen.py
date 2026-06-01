"""
快速测试 AI 生图功能（SiliconFlow → Pollinations 降级）
运行方式：
  python tools/test_image_gen.py
  python tools/test_image_gen.py --prompt "custom prompt here"
"""
import argparse
import os
import sys

# 把项目根目录加入 path，直接复用 purifier.py 的两个函数
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from purifier import generate_cover_prompt, generate_cover_image, COVERS_DIR, SILICONFLOW_API_KEY

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="", help="直接指定英文画面提示词（留空则用 DeepSeek 生成）")
    parser.add_argument("--title",  default="AI编程工具真实测评", help="文章标题（用于生成提示词）")
    parser.add_argument("--summary", default="三家机构独立验证，该工具对初级开发者提效40%，但复杂重构提升有限。", help="文章摘要")
    args = parser.parse_args()

    print(f"COVERS_DIR  : {COVERS_DIR}")
    print(f"SILICONFLOW : {'已配置 ✓' if SILICONFLOW_API_KEY else '未配置，将使用 Pollinations 降级'}")
    print()

    # 1. 生成提示词
    if args.prompt:
        prompt = args.prompt
        print(f"[跳过 DeepSeek] 使用手动提示词: {prompt}")
    else:
        print("[Step 1] 调用 DeepSeek Flash 生成封面提示词...")
        prompt = generate_cover_prompt(args.title, args.summary)
        print(f"  → 提示词: {prompt}")

    # 2. 生成图片
    print("\n[Step 2] 生成封面图片...")
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    result = generate_cover_image(prompt, "test-cover")

    if result:
        print(f"\n✅ 成功！图片路径: {result}")
        abs_path = COVERS_DIR / "test-cover.jpg"
        print(f"   本地文件: {abs_path}  ({abs_path.stat().st_size // 1024} KB)")
    else:
        print("\n❌ 生图失败，请检查网络或 API Key")

if __name__ == "__main__":
    main()
