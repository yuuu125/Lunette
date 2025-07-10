# -*- coding: utf-8 -*-
"""AI Meeting Assistant Core Pipeline (Stable Version).ipynb"""

# ===== 1. 安装依赖 =====
# 使用兼容性更好的版本组合
!pip install openai == 0.28.1 python - docx notion - client langdetect

# ===== 2. 导入库 =====
import os
import re
import json
import openai  # 使用0.28版本的API
from docx import Document
from google.colab import files, userdata
from notion_client import Client
from langdetect import detect, LangDetectException
import datetime

# ===== 3. 配置常量 =====
# 安全地从Colab密钥管理获取API密钥
try:
    OPENAI_API_KEY = userdata.get('OPENAI_API_KEY')
    NOTION_TOKEN = userdata.get('NOTION_TOKEN')
    NOTION_DB_ID = userdata.get('NOTION_DB_ID')

    # 验证密钥是否获取成功
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY未设置，请通过左侧钥匙图标添加密钥")
    if not NOTION_TOKEN:
        print("⚠️ Notion令牌未设置，Notion功能将禁用")
    if not NOTION_DB_ID:
        print("⚠️ Notion数据库ID未设置，Notion功能将禁用")

    # 设置OpenAI API密钥
    openai.api_key = OPENAI_API_KEY
    print("✅ OpenAI API密钥已设置")

except Exception as e:
    print(f"❌ 密钥获取失败: {str(e)}")
    # 作为备选，您可以直接在这里设置密钥（不推荐）
    # OPENAI_API_KEY = "sk-..."
    # NOTION_TOKEN = "secret_..."
    # NOTION_DB_ID = "123456..."
    # openai.api_key = OPENAI_API_KEY


# ===== 4. 文本输入模块 =====
def handle_transcript_input():
    """处理文本输入：上传文件或粘贴文本"""
    print("\n=== 处理会议记录输入 ===")

    input_method = input("选择输入方式 (1-上传文件, 2-粘贴文本): ")
    transcript_text = ""

    # 选项1：文件上传
    if input_method == "1":
        uploaded = files.upload()
        if not uploaded:
            print("⚠️ 未上传文件，使用粘贴文本方式")
            transcript_text = input("粘贴会议记录文本: ")
        else:
            filename = list(uploaded.keys())[0]
            print(f"✅ 已上传文件: {filename}")

            # 处理文本文件
            if filename.endswith('.txt'):
                transcript_text = uploaded[filename].decode('utf-8')

            # 处理Word文档
            elif filename.endswith('.docx'):
                doc = Document(filename)
                transcript_text = "\n".join([para.text for para in doc.paragraphs])

            else:
                raise ValueError("不支持的文件格式，请使用.txt或.docx")

    # 选项2：粘贴文本
    elif input_method == "2":
        transcript_text = input("粘贴会议记录文本: ")

    # 清理文本
    cleaned_text = clean_transcript(transcript_text)
    segments = segment_text(cleaned_text)

    print(f"📝 文本处理完成: {len(segments)}个段落")
    return cleaned_text, segments


# 添加测试连接函数
def test_notion_connection():
    try:
        notion = Client(auth=NOTION_TOKEN)
        db_info = notion.databases.retrieve(database_id=NOTION_DB_ID)
        print("✅ Notion连接成功!")
        print(f"数据库名称: {db_info['title'][0]['text']['content']}")
        print("数据库属性:", list(db_info['properties'].keys()))
        return True
    except Exception as e:
        print(f"❌ Notion连接失败: {str(e)}")
        return False


def clean_transcript(text):
    """清理文本：移除时间戳和说话人标识"""
    # 移除时间戳 (00:00:00格式)
    text = re.sub(r'\d{1,2}:\d{2}:\d{2}', '', text)
    # 移除说话人标识 (Speaker 1:)
    text = re.sub(r'Speaker\s*\d+:?', '', text)
    # 移除多余空行
    return re.sub(r'\n\s*\n', '\n\n', text).strip()


def segment_text(text):
    """简单分段逻辑"""
    return [p.strip() for p in text.split('\n\n') if p.strip()]


# ===== 5. GPT摘要和关键点提取 (使用0.28版本API) =====
def analyze_with_gpt(text, language='en'):
    """使用GPT分析会议记录"""
    print("\n=== 使用GPT分析会议记录 ===")

    if not openai.api_key:
        print("❌ OpenAI API密钥未设置，无法进行分析")
        return {"error": "OpenAI API密钥未设置", "fallback_used": True}, 0

    # 多语言支持
    lang_map = {'zh': 'Chinese', 'es': 'Spanish', 'fr': 'French', 'en': 'English'}
    lang_name = lang_map.get(language[:2], 'English')

    # 系统提示词 - 增强版，添加会议标题和参会人提取
    system_prompt = f"""
    你是一个专业的会议分析师，请从以下会议记录中提取关键信息：
    - 使用{lang_name}回复
    - 如果无法识别语言，使用英语
    - 按以下JSON格式回复：
    {{
        "meeting_title": "会议标题",
        "participants": ["参会人1", "参会人2", ...],
        "summary": "会议摘要",
        "action_items": [{{"task": "任务描述", "assignee": "负责人"}}],
        "key_points": {{
            "concerns": [],
            "decisions": [],
            "deadlines": [],
            "updates": []
        }},
        "meeting_type": "会议类型",
        "platform": "会议平台",
        "fallback_used": false
    }}

    提取规则：
    1. meeting_title: 从会议记录开头或结尾提取会议标题，如未明确提及则根据内容生成简洁标题
    2. participants: 提取所有参会人姓名，优先提取明确提到的参会人列表
    3. 重点关注会议开头和结尾部分，这些地方通常包含会议标题和参会人信息
    """

    # 用户提示词
    user_prompt = f"会议记录：\n{text[:10000]}"  # 限制长度

    try:
        # 使用0.28版本的API调用
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3
        )

        # 解析响应
        content = response.choices[0].message['content']
        result = json.loads(content)
        tokens_used = response.usage['total_tokens']

        print(f"✅ GPT分析完成! 使用token: {tokens_used}")
        print(f"会议标题: {result.get('meeting_title', '未知')}")
        print(f"参会人数: {len(result.get('participants', []))}")
        print(f"会议类型: {result.get('meeting_type', '未知')}")
        print(f"行动项数量: {len(result.get('action_items', []))}")

        # 行动项回退机制
        if not result.get('action_items'):
            result['fallback_used'] = True
            print("⚠️ 未检测到行动项，启用回退机制")

        return result, tokens_used

    except Exception as e:
        print(f"❌ GPT分析失败: {str(e)}")
        return {
            "error": str(e),
            "fallback_used": True
        }, 0


# ===== 6. Notion数据库集成 =====
def create_notion_entry(meeting_data):
    """在Notion数据库中创建条目"""
    if not NOTION_TOKEN or not NOTION_DB_ID:
        print("⚠️ Notion配置不完整，跳过同步")
        return False

    print("\n=== 同步到Notion数据库 ===")

    try:
        notion = Client(auth=NOTION_TOKEN)

        # 准备属性 - 使用自动提取的会议标题和参会人
        properties = {
            "Meeting Title": {"title": [{"text": {"content": meeting_data.get("meeting_title", "未命名会议")}}]},
            "Participant": {
                "rich_text": [{"text": {"content": ", ".join(meeting_data.get("participants", ["未知"]))}}]},
            "Date & Duration": {"date": {"start": meeting_data.get("date", datetime.datetime.now().isoformat())}},
            "Meeting Type": {"select": {"name": meeting_data.get("meeting_type", "其他")}},
            "Platform": {"select": {"name": meeting_data.get("platform", "未知平台")}},
            "Summary": {"rich_text": [{"text": {"content": meeting_data.get("summary", "")}}]},
            "Key Points": {"rich_text": [{"text": {"content": format_key_points(meeting_data)}}]},
            "Action Items": {"rich_text": [{"text": {"content": format_action_items(meeting_data)}}]},
        }

        # 创建新条目
        new_page = notion.pages.create(
            parent={"database_id": NOTION_DB_ID},
            properties=properties
        )

        print(f"✅ Notion条目创建成功! ID: {new_page['id']}")
        return True
    except Exception as e:
        print(f"❌ Notion同步失败: {str(e)}")
        return False


def format_key_points(data):
    """格式化关键点"""
    points = []
    key_points = data.get("key_points", {})
    for category, items in key_points.items():
        if items and isinstance(items, list):
            points.append(f"{category.upper()}:")
            points.extend([f"- {item}" for item in items])
    return "\n".join(points)


def format_action_items(data):
    """格式化行动项"""
    action_items = data.get("action_items", [])
    if not action_items or not isinstance(action_items, list):
        return "无明确行动项"

    formatted = []
    for item in action_items:
        if isinstance(item, dict):
            task = item.get('task', '未知任务')
            assignee = item.get('assignee', '待分配')
            formatted.append(f"- {task} (负责人: {assignee})")
        else:
            formatted.append(f"- {str(item)}")
    return "\n".join(formatted)


# ===== 7. Whisper集成（准备阶段） =====
def setup_whisper():
    """安装Whisper并测试"""
    print("\n=== 准备Whisper语音识别 ===")
    !pip
    install
    git + https: // github.com / openai / whisper.git
    !sudo
    apt
    update & & sudo
    apt
    install
    ffmpeg

    # 测试音频上传
    uploaded_audio = files.upload()
    if uploaded_audio:
        audio_file = list(uploaded_audio.keys())[0]
        print(f"🔊 音频样本已上传: {audio_file}")
        return audio_file
    return None


# ===== 8. 主工作流程 =====
def main():
    """核心工作流程"""
    if not openai.api_key:
        print("❌ OpenAI API密钥未设置，无法运行工作流程")
        return

    logs = {"steps": [], "errors": []}

    # 在开始处添加连接测试
    if NOTION_TOKEN and NOTION_DB_ID:
        if not test_notion_connection():
            print("⚠️ Notion连接失败，请检查配置")

    try:
        # 步骤1: 输入处理
        cleaned_text, segments = handle_transcript_input()
        logs["steps"].append({
            "step": "文本输入",
            "segment_count": len(segments),
            "status": "success"
        })

        # 步骤2: GPT分析
        try:
            # 尝试检测语言
            language = detect(cleaned_text[:500]) if cleaned_text else 'en'
        except LangDetectException:
            language = 'en'

        gpt_results, tokens_used = analyze_with_gpt(cleaned_text, language)

        # 处理可能的GPT错误
        if "error" in gpt_results:
            logs["steps"].append({
                "step": "GPT分析",
                "status": "failed",
                "error": gpt_results["error"]
            })
            print(f"❌ GPT分析失败: {gpt_results['error']}")
            return
        else:
            logs["steps"].append({
                "step": "GPT分析",
                "tokens_used": tokens_used,
                "meeting_title": gpt_results.get("meeting_title"),
                "participants_count": len(gpt_results.get("participants", [])),
                "meeting_type": gpt_results.get("meeting_type"),
                "action_items_count": len(gpt_results.get("action_items", [])),
                "status": "success"
            })

        # 步骤3: Notion同步
        # 添加日期信息
        gpt_results["date"] = datetime.datetime.now().isoformat()

        # 创建Notion条目
        notion_success = create_notion_entry(gpt_results)
        logs["steps"].append({
            "step": "Notion同步",
            "status": "success" if notion_success else "failed"
        })

        # 保存日志
        with open("meeting_logs.json", "w") as f:
            json.dump(logs, f, indent=2)

        print("\n✅ 流程完成! 日志已保存")

    except Exception as e:
        logs["errors"].append(str(e))
        print(f"\n❌ 流程出错: {str(e)}")
        with open("error_log.json", "w") as f:
            json.dump(logs, f, indent=2)


# ===== 9. 执行主函数 =====
if __name__ == "__main__":
    main()