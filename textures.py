import zipfile
import json

def find_all_textures(file_object, filename):
    item_paths = set()
    block_paths = set()
    entity_paths = set()
    json_found = False
    error_msg = None

    try:
        with zipfile.ZipFile(file_object, 'r') as archive:
            all_files = archive.namelist()
            
            # --- 1. ค้นหา Item Textures ---
            item_files = [f for f in all_files if f.lower().endswith('item_texture.json')]
            for json_file in item_files:
                json_found = True
                try:
                    with archive.open(json_file) as f:
                        data = json.load(f)
                        for item_name, item_info in data.get("texture_data", {}).items():
                            textures = item_info.get("textures")
                            if isinstance(textures, str): item_paths.add(textures)
                            elif isinstance(textures, list):
                                for tex in textures:
                                    if isinstance(tex, str): item_paths.add(tex)
                except: pass

            # --- 2. ค้นหา Block Textures ---
            block_files = [f for f in all_files if f.lower().endswith('terrain_texture.json')]
            for json_file in block_files:
                json_found = True
                try:
                    with archive.open(json_file) as f:
                        data = json.load(f)
                        for block_name, block_info in data.get("texture_data", {}).items():
                            textures = block_info.get("textures")
                            if isinstance(textures, str): block_paths.add(textures)
                            elif isinstance(textures, list):
                                for tex in textures:
                                    if isinstance(tex, str): block_paths.add(tex)
                            elif isinstance(textures, dict): # บล็อกแบบแยกด้าน (up, down, side)
                                for k, tex in textures.items():
                                    if isinstance(tex, str): block_paths.add(tex)
                except: pass

            # --- 3. ค้นหา Entity Textures ---
            # Entity จะอยู่ในโฟลเดอร์ entity/ หรือ client_entity/ ของ RP
            entity_files = [f for f in all_files if ('entity/' in f.lower() or 'client_entity/' in f.lower()) and f.lower().endswith('.json')]
            for json_file in entity_files:
                json_found = True
                try:
                    with archive.open(json_file) as f:
                        data = json.load(f)
                        # เข้าถึง path ของ Entity Texture
                        client_entity = data.get("minecraft:client_entity", {})
                        textures = client_entity.get("description", {}).get("textures", {})
                        for tex_key, tex_path in textures.items():
                            if isinstance(tex_path, str): entity_paths.add(tex_path)
                except: pass
                
    except zipfile.BadZipFile:
        error_msg = f"ข้อผิดพลาด: ไฟล์ {filename} ไม่ใช่ไฟล์บีบอัดที่สมบูรณ์"
    except Exception as e:
        error_msg = f"เกิดข้อผิดพลาดกับไฟล์ {filename}: {e}"
        
    # จัดกลุ่มส่งค่ากลับเป็น Dictionary เพื่อให้เอาไปแสดงผลง่ายๆ
    results_dict = {
        "items": sorted(list(item_paths)),
        "blocks": sorted(list(block_paths)),
        "entities": sorted(list(entity_paths))
    }
    
    return results_dict, json_found, error_msg