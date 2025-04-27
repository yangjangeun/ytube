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
    # 불필요한 문자 제거
    text = re.sub(r'[\n\r\t]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def translate_text_safely(text):
    if not text.strip():
        return text
        
    try:
        # 텍스트를 더 작은 단위로 분할 (최대 1000자)
        chunks = []
        current_chunk = []
        current_length = 0
        
        # 문장 단위로 분할
        sentences = re.split(r'([.!?।])', text)
        
        for i in range(0, len(sentences), 2):
            sentence = sentences[i]
            if i + 1 < len(sentences):
                sentence += sentences[i + 1]  # 구둣점 추가
            
            sentence = sentence.strip()
            if not sentence:
                continue
                
            # 청크 크기 제한
            if current_length + len(sentence) > 1000:
                if current_chunk:
                    chunks.append(' '.join(current_chunk))
                    current_chunk = []
                    current_length = 0
                    
                # 긴 문장은 추가로 분할
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
            
        # 번역 수행
        translated_parts = []
        for chunk in chunks:
            try:
                # 언어 감지
                detected = translator.detect(chunk)
                if detected and detected.lang == 'ko':
                    translated_parts.append(chunk)
                    continue
                    
                # 3번까지 번역 재시도
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
        
        # 번역 결과 정리
        translated_text = re.sub(r'\s*([.!?])\s*', r'\1 ', translated_text)  # 구둣점 정리
        translated_text = re.sub(r'\s+', ' ', translated_text)  # 중복 공백 제거
        
        return translated_text.strip()
        
    except Exception as e:
        print(f"번역 중 오류 발생: {str(e)}")
        return text

def get_available_transcript(video_id):
    """모든 가능한 자막을 가져오고 상세 정보를 로깅"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # 한국어 자막 시도
        try:
            transcript = transcript_list.find_transcript(['ko'])
            print("한국어 자막 발견")
            return transcript.fetch(), True
        except NoTranscriptFound:
            print("한국어 자막을 찾을 수 없습니다.")
            
            # 다른 자막 찾기
            available_transcripts = []
            
            # 수동 자막 찾기
            try:
                for lang, trans in transcript_list._manually_created_transcripts.items():
                    print(f"수동 자막 발견: {lang}")
                    available_transcripts.append(trans)
            except:
                pass
                
            # 자동 자막 찾기
            try:
                for lang, trans in transcript_list._generated_transcripts.items():
                    print(f"자동 자막 발견: {lang}")
                    available_transcripts.append(trans)
            except:
                pass
            
            if available_transcripts:
                # 첫 번째 가용 자막 사용
                selected_transcript = available_transcripts[0]
                print(f"선택된 자막: {selected_transcript.language}")
                return selected_transcript.fetch(), False
                
            raise NoTranscriptFound("사용 가능한 자막이 없습니다.")
            
    except Exception as e:
        print(f"자막 가져오기 오류: {str(e)}")
        raise

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_video():
    try:
        url = request.json.get('url', '')
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL을 입력해주세요.'
            })

        video_id = get_video_id(url)
        if not video_id:
            return jsonify({
                'success': False,
                'error': '올바른 YouTube URL이 아닙니다.'
            })

        try:
            transcript, is_korean = get_available_transcript(video_id)
            
            # 자막 텍스트 추출
            full_text = []
            
            for entry in transcript:
                # FetchedTranscriptSnippet 객체 처리
                if hasattr(entry, 'text'):
                    text = entry.text
                elif isinstance(entry, dict):
                    text = entry.get('text', '')
                else:
                    continue
                    
                text = clean_text(text)
                if text:
                    full_text.append(text)
            
            if not full_text:
                print("자막 텍스트를 추출할 수 없습니다.")
                return jsonify({
                    'success': False,
                    'error': '자막을 추출할 수 없습니다.'
                })

            full_text = ' '.join(full_text)

            # 한국어가 아닌 경우 번역
            if not is_korean:
                translated = translate_text_safely(full_text)
            else:
                translated = full_text

            return jsonify({
                'success': True,
                'original': full_text,
                'translated': translated
            })

        except (TranscriptsDisabled, NoTranscriptFound) as e:
            print(f"자막 없음: {str(e)}")
            return jsonify({
                'success': False,
                'error': '이 동영상에는 자막이 없습니다.'
            })
        except Exception as e:
            print(f"자막 처리 오류: {str(e)}")
            return jsonify({
                'success': False,
                'error': '자막을 처리하는 중 오류가 발생했습니다.'
            })

    except Exception as e:
        print(f"처리 중 오류 발생: {str(e)}")
        return jsonify({
            'success': False,
            'error': '처리 중 오류가 발생했습니다. 다시 시도해주세요.'
        })

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)