"""
스프라이트 이미지 크기 조정 스크립트
assets/ 폴더의 모든 PNG 파일을 2/3 크기로 축소합니다.

사용법:
    python resize_sprites.py
"""

from pathlib import Path
from PIL import Image
import sys

# 크기 비율 (2/3)
SCALE_RATIO = 2/3


def resize_sprites():
    """assets 폴더의 모든 PNG 파일을 2/3 크기로 축소"""
    
    assets_path = Path(__file__).parent.parent / "assets"
    
    if not assets_path.exists():
        print(f"❌ assets 폴더 없음: {assets_path}")
        return False
    
    print(f"📂 asset 폴더: {assets_path}")
    print(f"📐 크기 비율: {SCALE_RATIO:.1%}")
    
    # 모든 PNG 파일 찾기
    png_files = list(assets_path.rglob("*.png"))
    
    if not png_files:
        print("❌ PNG 파일을 찾을 수 없습니다.")
        return False
    
    print(f"🖼️  찾은 PNG 파일: {len(png_files)}개\n")
    
    success_count = 0
    error_count = 0
    
    for png_file in png_files:
        try:
            # 이미지 로드
            img = Image.open(png_file)
            original_size = img.size
            
            # 새 크기 계산
            new_width = int(img.width * SCALE_RATIO)
            new_height = int(img.height * SCALE_RATIO)
            
            # 이미지 축소 (고품질 리샘플링)
            resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 원본 파일에 덮어쓰기
            resized_img.save(png_file, "PNG", quality=95)
            
            print(f"✅ {png_file.name:30s} | {original_size} → {(new_width, new_height)}")
            success_count += 1
            
        except Exception as e:
            print(f"❌ {png_file.name:30s} | 오류: {str(e)}")
            error_count += 1
    
    print(f"\n{'='*70}")
    print(f"✅ 성공: {success_count}개")
    print(f"❌ 실패: {error_count}개")
    print(f"{'='*70}\n")
    
    return error_count == 0


if __name__ == "__main__":
    success = resize_sprites()
    sys.exit(0 if success else 1)
