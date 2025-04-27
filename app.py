from flask import Flask, render_template, request, jsonify
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from googletrans import Translator
import re

app = Flask(__name__)
translator = Translator()

def get_video_id(url):
    try:
        if 'youtube.com' in url:
            if 'v=' in url:
                return url.split('v=')[1].split('&')[0]
            elif 'embed/' in url:
                return url.split('embed/')[1].split('?')[0]
        elif 'youtu.be' in url:
            return url.split('/')[-1].split('?')[0]
        return url
    except:
        return url

def clean_text(text):
    text = re.sub(r'[\n\r\t]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def translate_text_safely(text):
    if not text.strip():
        return text
    try:
        chunks = []
        current_chunk = []
        current_length = 0
        sentences = re.split(r'([.!?।])', text)
        for i in range(0, len(sentences), 2):
            sentence = sentences[i]
            if i + 1 < len(sentences):
                sentence += sentences[i + 1]
            sentence = sentence.strip()
            if not sentence:
                continue
            if current_length + len(sentence) > 1000:
                if current_chunk:
                    chunks.append(' '.join(current_chunk))
                    current_chunk = []
                    current_length = 0
                if len(sentence) > 1000:
                    words = sentence.split()
                    temp_chunk = []
                    temp_length = 0
                    for word in words:
                        if temp_length + len(word) > 1000:
                            chunks.append(' '.join(temp_chunk))
                            temp_chunk = [word]
                            temp_length = len(word)
                        else:
                            temp_chunk.append(word)
                            temp_length += len(word) + 1
                    if temp_chunk:
                        chunks.append(' '.join(temp_chunk))
                else:
                    current_chunk.append(sentence)
                    current_length = len(sentence)
            else:
                current_chunk.append(sentence)
                current_length += len(sentence) + 1
        if current_chunk:
            chunks.append(' '.join(current_chunk))
        translated_parts = []
        for chunk in chunks:
            try:
                detected = translator.detect(chunk)
                if detected and detected.lang == 'ko':
                    translated_parts.append(chunk)
                    continue
                for attempt in range(3):
                    try:
                        result = translator.translate(chunk, dest='ko')
                        if result and result.text:
                            translated_parts.append(result.text)
                            break
                    except Exception as e:
                        print(f"번역 시도 {attempt + 1} 실패: {str(e)}")
                        if attempt == 2:
                            translated_parts.append(chunk)
                        continue
            except Exception as e:
                print(f"청크 번역 오류: {str(e)}")
                translated_parts.append(chunk)
        translated_text = ' '.join(translated_parts)
        translated_text = re.sub(r'\s*([.!?])\s*', r'\1 ', translated_text)
        translated_text = re.sub(r'\s+', ' ', translated_text)
        return translated_text.strip()
    except Exception as e:
        print(f"번역 중 오류 발생: {str(e)}")
        return text

def get_available_transcript(video_id):
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript(['ko'])
            return transcript.fetch(), True
        except NoTranscriptFound:
            available_transcripts = []
            try:
                for lang, trans in transcript_list._manually_created_transcripts.items():
                    available_transcripts.append(trans)
            except:
                pass
            try:
                for lang, trans in transcript_list._generated_transcripts.items():
                    available_transcripts.append(trans)
            except:
                pass
            if available_transcripts:
                selected_transcript = available_transcripts[0]
                return selected_transcript.fetch(), False
            raise NoTranscriptFound("사용 가능한 자막이 없습니다.")
    except Exception as e:
        print(f"자막 가져오기 오류: {str(e)}")
        raise

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/extract', methods=['POST'])
def extract_text():
    try:
        url = request.json.get('url', '')
        lang = request.json.get('lang', 'auto')
        if not url:
            return jsonify({'error': 'URL을 입력해주세요.'}), 400
        video_id = get_video_id(url)
        if not video_id:
            return jsonify({'error': '올바른 YouTube URL이 아닙니다.'}), 400
        transcript, _ = get_available_transcript(video_id)
        full_text = []
        for entry in transcript:
            text = entry.text if hasattr(entry, 'text') else entry.get('text', '')
            text = clean_text(text)
            if text:
                full_text.append(text)
        if not full_text:
            return jsonify({'error': '자막을 추출할 수 없습니다.'}), 400
        return jsonify({'text': ' '.join(full_text)})
    except Exception as e:
        print(f"extract_text 오류: {str(e)}")
        return jsonify({'error': '자막 추출 중 오류가 발생했습니다.'}), 500

@app.route('/translate', methods=['POST'])
def translate():
    try:
        url = request.json.get('url', '')
        lang = request.json.get('lang', 'auto')
        if not url:
            return jsonify({'error': 'URL을 입력해주세요.'}), 400
        video_id = get_video_id(url)
        if not video_id:
            return jsonify({'error': '올바른 YouTube URL이 아닙니다.'}), 400
        transcript, is_korean = get_available_transcript(video_id)
        full_text = []
        for entry in transcript:
            text = entry.text if hasattr(entry, 'text') else entry.get('text', '')
            text = clean_text(text)
            if text:
                full_text.append(text)
        if not full_text:
            return jsonify({'error': '자막을 추출할 수 없습니다.'}), 400
        full_text = ' '.join(full_text)
        if not is_korean:
            translated = translate_text_safely(full_text)
        else:
            translated = full_text
        return jsonify({'text': translated})
    except Exception as e:
        print(f"translate 오류: {str(e)}")
        return jsonify({'error': '번역 중 오류가 발생했습니다.'}), 500

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
