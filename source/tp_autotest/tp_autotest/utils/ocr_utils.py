# -*- coding: utf-8 -*-
import time
import cv2
import os
import numpy as np
from paddleocr import PaddleOCR
from airtest.core.error import TargetNotFoundError
from tp_autotest.utils.airtest_api import try_log_screen, save_screen

class OcrHelper:
    """
    一个封装了所有OCR相关功能的帮助类。
    """
    def __init__(self, driver):
        self.driver = driver
        self.ocr_instance = None

    @property
    def ocr(self):
        """延迟初始化PaddleOCR实例，只在第一次使用时加载。"""
        if self.ocr_instance is None:
            print("Initializing PaddleOCR...")
            model_base_path = os.path.join(os.environ.get("ProgramFiles", "C:/Program Files"),"Automa/paddleocr/whl/")
            det_model_path = os.path.join(model_base_path, 'det', 'en', 'en_PP-OCRv3_det_infer')
            rec_model_path = os.path.join(model_base_path, 'rec', 'en', 'en_PP-OCRv4_rec_infer')
            cls_model_path = os.path.join(model_base_path, 'cls', 'en', 'ch_ppocr_mobile_v2.0_cls_infer')

            self.ocr_instance = PaddleOCR(
                use_angle_cls=True,
                lang='en', 
                show_log=False,
                det_model_dir=det_model_path,
                rec_model_dir=rec_model_path,
                cls_model_dir=cls_model_path
            )
            # self.ocr_instance = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
        return self.ocr_instance

    def get_all_ocr_results(self, screen=None):
        """执行一次全屏OCR并返回所有结果的结构化列表。"""
        if screen is None:
            screen = self.driver.screenshot()
        
        if screen is None:
            return []

        ocr_results = self.ocr.ocr(screen, cls=False)
        if not ocr_results or not ocr_results[0]:
            return []

        structured_results = []
        for line in ocr_results[0]:
            points = line[0]
            text = line[1][0]
            confidence = line[1][1]
            x_coords = [p[0] for p in points]
            y_coords = [p[1] for p in points]
            
            structured_results.append({
                'text': text,
                'confidence': confidence,
                'center': (sum(x_coords) / 4, sum(y_coords) / 4),
                'box': points,
                'height': max(y_coords) - min(y_coords),
                'width': max(x_coords) - min(x_coords),
                'corners': {
                    'tl': (min(x_coords), min(y_coords)), # Top-Left
                    'tr': (max(x_coords), min(y_coords)), # Top-Right
                    'bl': (min(x_coords), max(y_coords)), # Bottom-Left
                    'br': (max(x_coords), max(y_coords)), # Bottom-Right
                }
            })
        self.visualize_all_ocr_results(screen)
        return structured_results

    def ocr_find_elements(self, text, offset=None):
        """
        通过OCR查找所有包含指定文本的元素。

        :param text: 要查找的文字
        :return: list[OcrElement] 一个包含OcrElement实例的列表
        """
        from tp_autotest.proxy import OcrElement
        screen = self.driver.screenshot()
        all_results = self.get_all_ocr_results(screen)

        candidates = []
        for box in all_results:
            if text.lower() in box['text'].lower():
                candidates.append(box)
        if not candidates:
            return []
        candidates.sort(key=lambda b: (-(b['text'] == text), b['corners']['tl'][1], b['corners']['tl'][0]))

        # 生成带所有元素编号的概览截图日志
        screen_with_highlights = screen.copy()
        for i, box in enumerate(candidates):
            points = np.array(box['box'], dtype=np.int32)
            cv2.polylines(screen_with_highlights, [points], isClosed=True, color=(69, 53, 220), thickness=1)
            label = f"[{i}]"
            top_left_corner = tuple(points[0])
            cv2.putText(screen_with_highlights, label, (top_left_corner[0], top_left_corner[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (69, 53, 220), 1)

        element_list = []
        for box_data in candidates:
            log_res = save_screen(screen_with_highlights)
            if offset and offset != (0, 0) and 'center' in box_data and isinstance(box_data['center'], (list, tuple)) and len(box_data['center']) == 2:
                final_center = (box_data['center'][0] + offset[0], box_data['center'][1] + offset[1])
                log_res = self.visualiza_log_path(screen_with_highlights, [box_data['center'],final_center], offset)
                box_data['center'] = final_center
            element_list.append(OcrElement(self.driver, box_data, log_res))

        return element_list

    def find_text(self, text, offset=(0,0), timeout=10, interval=0.5):
        """在屏幕上循环查找指定的文字，直到超时。"""
        start_time = time.time()
        while True:
            screen = self.driver.screenshot()
            if screen is None:
                print("Screen is None, may be locked")
            else:
                ocr_results = self.get_all_ocr_results(screen)
                candidates = []
                for box in ocr_results:
                    if text.lower() in box['text'].lower():
                        candidates.append(box)
                if candidates:
                    candidates.sort(key=lambda b: (-(b['text'] == text), b['corners']['tl'][1], b['corners']['tl'][0]))
                    best_match_box = candidates[0]
                    match_pos = best_match_box['center']
                    points = best_match_box['box']
                    x_coords = [p[0] for p in points]
                    y_coords = [p[1] for p in points]

                    screen_with_rect = screen
                    cv2.rectangle(screen_with_rect, (int(min(x_coords)), int(min(y_coords))), (int(max(x_coords)), int(max(y_coords))), (143, 143, 246), 2)
                    match_pos = (match_pos[0] + offset[0], match_pos[1] + offset[1])
                    try_log_screen(screen_with_rect,pos=[match_pos])
                    return match_pos

            if (time.time() - start_time) > timeout:
                try_log_screen(screen)
                raise TargetNotFoundError('文字 "%s" 在屏幕上未找到' % text)
            else:
                time.sleep(interval)


    def ocr_find_element_by_step(self, text, steps=None, offset=None, timeout=10):
        """
        在指定时间内循环查找，预处理布局，然后分步查找，并应用最终偏移。
        """
        from tp_autotest.proxy import OcrElement
        start_time = time.time()
        last_exception = None

        while time.time() - start_time < timeout:
            screen = self.driver.screenshot()
            if screen is None:
                time.sleep(0.5)
                continue
            
            all_results = self.get_all_ocr_results(screen)
            candidates = []
            for box in all_results:
                if text.lower() in box['text'].lower():
                    candidates.append(box)
            
            if not candidates:
                last_exception = TargetNotFoundError(f'在屏幕上找不到任何包含 "{text}" 的文字')
                time.sleep(0.5)
                continue

            candidates.sort(key=lambda b: (-(b['text'] == text), b['corners']['tl'][1], b['corners']['tl'][0]))
            current_box = candidates[0]
            path_coords = [current_box['center']]
            
            try:
                if steps:
                    all_rows = self._group_elements_into_rows(all_results)
                    all_columns = self._group_elements_into_columns(all_results)
                    
                    for step in steps:
                        direction_map = {"up": "v", "down": "v", "left": "h", "right": "h", "的上边": "v", "的下边": "v", "的左边": "h", "的右边": "h"}
                        search_type = direction_map.get(step)

                        layout_data = all_rows if search_type == "v" else all_columns
                        best_candidate = self.find_element_in_layout(current_box, layout_data, step)
                        
                        if not best_candidate or 'center' not in best_candidate:
                            raise TargetNotFoundError(f'找不到"{current_box["text"]}" "{step}" 方向的元素')
                        current_box = best_candidate
                        path_coords.append(current_box['center'])

                if offset and offset != (0, 0) and 'center' in current_box and isinstance(current_box['center'], (list, tuple)) and len(current_box['center']) == 2:
                    final_center = (current_box['center'][0] + offset[0], current_box['center'][1] + offset[1])
                    current_box['center'] = final_center
                    path_coords.append(final_center)

                log = self.visualiza_log_path(screen, path_coords, offset)
                return OcrElement(self.driver, current_box, log)

            except TargetNotFoundError as e:
                last_exception = e
                time.sleep(0.5)
                continue
        if last_exception:
            raise last_exception
        else:
            raise TargetNotFoundError(f'在 {timeout} 秒内未能找到"{text}"相对元素')

    def _group_elements_into_rows(self, elements):
        """将所有OCR元素按Y坐标整理成行。"""
        if not elements: return []
        sorted_elements = sorted(elements, key=lambda e: e['corners']['tl'][1])
        rows = []
        if not sorted_elements: return rows
        current_row = [sorted_elements[0]]
        avg_height = sum(e.get('height', 10) for e in elements) / len(elements) if elements else 10
        row_gap_threshold = avg_height * 0.5
        for i in range(1, len(sorted_elements)):
            prev_element = current_row[-1]
            current_element = sorted_elements[i]
            vertical_mid_prev = prev_element['center'][1]
            vertical_mid_curr = current_element['center'][1]
            if abs(vertical_mid_curr - vertical_mid_prev) < row_gap_threshold:
                current_row.append(current_element)
            else:
                rows.append(sorted(current_row, key=lambda e: e['corners']['tl'][0]))
                current_row = [current_element]
        rows.append(sorted(current_row, key=lambda e: e['corners']['tl'][0]))
        return rows

    def _group_elements_into_columns(self, elements):
        """将所有OCR元素按X坐标整理成列。"""
        if not elements: return []
        sorted_elements = sorted(elements, key=lambda e: e['corners']['tl'][0])
        columns = []
        if not sorted_elements: return columns
        current_column = [sorted_elements[0]]
        avg_width = sum(e.get('width', 20) for e in elements) / len(elements) if elements else 20
        column_gap_threshold = avg_width * 0.5
        for i in range(1, len(sorted_elements)):
            prev_element = current_column[-1]
            current_element = sorted_elements[i]
            horizontal_mid_prev = prev_element['corners']['tl'][0]
            horizontal_mid_curr = current_element['corners']['tl'][0]
            if abs(horizontal_mid_curr - horizontal_mid_prev) < column_gap_threshold:
                current_column.append(current_element)
            else:
                columns.append(sorted(current_column, key=lambda e: e['corners']['tl'][1]))
                current_column = [current_element]
        columns.append(sorted(current_column, key=lambda e: e['corners']['tl'][1]))
        return columns
    
    def find_element_in_layout(self, origin_box, layout_data, direction_str):
        """
        在预处理好的行/列布局中执行查找。
        """
        def is_not_origin(c):
            return c is not origin_box

        DIRECTION_MAP = {"的左边": "left", "left": "left",
                         "的右边": "right", "right": "right",
                         "的上边": "up", "up": "up",
                         "的下边": "down", "down": "down"
                        }
        direction = DIRECTION_MAP.get(direction_str)

        if not direction: raise ValueError(f"Unknown direction step: {direction_str}")

        origin_unit_index = -1
        for i, unit in enumerate(layout_data):
            if origin_box in unit:
                origin_unit_index = i
                break
        if origin_unit_index == -1:
            return None

        # 上/下 查找 (基于“行”的逻辑)
        if direction in ["up", "down"]:
            target_units = layout_data[origin_unit_index + 1:] if direction == "down" else layout_data[:origin_unit_index][::-1]
            origin_x_min, origin_x_max = origin_box['corners']['tl'][0], origin_box['corners']['tr'][0]
            origin_width = origin_x_max - origin_x_min
            expansion_amount = origin_box.get('height', 10) * 5

            # 精确匹配：查找有直接重叠的元素
            for i, row in enumerate(target_units):
                candidates = [c for c in row if is_not_origin(c)]
                if not candidates: continue

                exact_matches = []
                for c in candidates:
                    overlap_width = max(0, min(origin_x_max, c['corners']['tr'][0]) - max(origin_x_min, c['corners']['tl'][0]))
                    if overlap_width > 0:
                        candidate_width = c['corners']['tr'][0] - c['corners']['tl'][0]
                        ratio_on_origin = overlap_width / origin_width if origin_width > 0 else 0
                        ratio_on_candidate = overlap_width / candidate_width if candidate_width > 0 else 0
                        final_ratio = max(ratio_on_origin, ratio_on_candidate)
                        exact_matches.append({'cand': c, 'overlap': overlap_width, 'ratio': final_ratio})
                        print(f"- Candidate: '{c['text']}' | Overlap: {overlap_width:.2f} | Final Ratio: {final_ratio:.4f}")
                
                # 只要在当前行找到任何一个重叠元素，就立即决策并返回，不再看后面的行
                if exact_matches:
                    best_match = max(exact_matches, key=lambda x: (x['ratio'], x['overlap']))
                    return best_match['cand']

            # 扩展匹配：如果没有精确匹配，则扩大范围搜索
            for i, row in enumerate(target_units):
                candidates = [c for c in row if is_not_origin(c)]
                if not candidates: continue

                exp_x_min, exp_x_max = origin_x_min - expansion_amount, origin_x_max + expansion_amount
                expanded_matches = []
                for c in candidates:
                    overlap_width = max(0, min(exp_x_max, c['corners']['tr'][0]) - max(exp_x_min, c['corners']['tl'][0]))
                    if overlap_width > 0:
                        dist = -abs(c['center'][0] - origin_box['center'][0])
                        expanded_matches.append({'cand': c, 'overlap': overlap_width, 'dist': dist})
                
                # 只要在当前行通过扩展找到了任何一个元素，就立即决策并返回
                if expanded_matches:
                    best_match = max(expanded_matches, key=lambda x: (x['overlap'], x['dist']))
                    return best_match['cand']


        # 左/右 查找 (基于“列”的逻辑)
        elif direction in ["left", "right"]:
            target_units = layout_data[origin_unit_index + 1:] if direction == "right" else layout_data[:origin_unit_index][::-1]
            origin_y_min, origin_y_max = origin_box['corners']['tl'][1], origin_box['corners']['bl'][1]
            origin_height = origin_y_max - origin_y_min
            expansion_amount = origin_box.get('height', 15)

            for i, col in enumerate(target_units):
                candidates = [c for c in col if is_not_origin(c)]
                if not candidates: continue
                exact_matches = []
                for c in candidates:
                    overlap_height = max(0, min(origin_y_max, c['corners']['bl'][1]) - max(origin_y_min, c['corners']['tl'][1]))
                    if overlap_height > 0:
                        candidate_height = c['corners']['bl'][1] - c['corners']['tl'][1]
                        ratio_on_origin = overlap_height / origin_height if origin_height > 0 else 0
                        ratio_on_candidate = overlap_height / candidate_height if candidate_height > 0 else 0
                        final_ratio = max(ratio_on_origin, ratio_on_candidate)
                        exact_matches.append({'cand': c, 'overlap': overlap_height, 'ratio': final_ratio})
                if exact_matches:
                    best_match = max(exact_matches, key=lambda x: (x['ratio'], x['overlap']))
                    return best_match['cand']

            for i, col in enumerate(target_units):
                candidates = [c for c in col if is_not_origin(c)]
                if not candidates: continue
                exp_y_min, exp_y_max = origin_y_min - expansion_amount, origin_y_max + expansion_amount
                expanded_matches = []
                for c in candidates:
                     overlap_height = max(0, min(exp_y_max, c['corners']['bl'][1]) - max(exp_y_min, c['corners']['tl'][1]))
                     if overlap_height > 0:
                        dist = -abs(c['center'][1] - origin_box['center'][1])
                        expanded_matches.append({'cand': c, 'overlap': overlap_height, 'dist': dist})
                if expanded_matches:
                    best_match = max(expanded_matches, key=lambda x: (x['overlap'], x['dist']))
                    return best_match['cand']
                    
        return None

    def visualiza_log_path(self, screen, path_coords, offset):
        """
        在截图上绘制查找路径并记录到Airtest报告。
        """
        # 如果路径点不止一个，绘制箭头路径
        if len(path_coords) > 1:
            for i in range(len(path_coords) - 1):
                p1 = (int(path_coords[i][0]), int(path_coords[i][1]))
                p2 = (int(path_coords[i+1][0]), int(path_coords[i+1][1]))
                cv2.arrowedLine(screen, p1, p2, (128, 128, 255), 1, tipLength=0.03)

        # 标记起点和终点
        start_point = (int(path_coords[0][0]), int(path_coords[0][1]))
        end_point = (int(path_coords[-1][0]), int(path_coords[-1][1]))
        cv2.circle(screen, start_point, 6, (0, 0, 255), -1)
        cv2.circle(screen, end_point, 6, (0, 0, 255), -1)
        
        if offset and offset != (0, 0):
            offset_start_point = (int(path_coords[-2][0]), int(path_coords[-2][1]))
            cv2.arrowedLine(screen, offset_start_point, end_point, (0, 255, 0), 1, tipLength=0.01)
            cv2.circle(screen, offset_start_point, 2, (128, 255, 128), -1)
            cv2.circle(screen, end_point, 6, (0, 255, 0), -1)

        # 记录日志，并高亮终点位置
        return save_screen(screen, pos=[end_point])

    def visualize_all_ocr_results(self, screen=None):
        """
        执行一次全屏OCR，并将所有识别结果的边框和文字绘制在截图上，然后保存。
        
        :param screen: 可选，如果提供，则使用此图像；否则将进行新的截图。
        :param output_dir: 可选，保存可视化结果的目录。
        :return: 保存的图片文件的完整路径。
        """
        if screen is None:
            screen = self.driver.screenshot()
        
        if screen is None:
            print("Screen is None, cannot visualize.")
            return None

        ocr_raw_results = self.ocr.ocr(screen, cls=False)
        # 创建一个副本用于绘制
        image_with_boxes = screen.copy()

        if ocr_raw_results and ocr_raw_results[0]:
            all_boxes_data = ocr_raw_results[0]
            for i, line_data in enumerate(all_boxes_data):
                points = line_data[0]
                text = line_data[1][0]
                confidence = line_data[1][1]

                box_points = np.array(points, dtype=np.int32)
                cv2.polylines(image_with_boxes, [box_points], isClosed=True, color=(0, 0, 255), thickness=1)

                label = f"[{i}] {text} ({confidence:.2f})"
                
                top_left_corner = tuple(box_points[0])
                (text_width, text_height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.3, 1)
                
                label_origin_y = top_left_corner[1] + 1
                if label_origin_y < text_height:
                    label_origin_y = top_left_corner[1] + text_height + baseline
                
                cv2.putText(image_with_boxes, label, (top_left_corner[0], label_origin_y - 5), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (69, 53, 220), 1)

        return save_screen(image_with_boxes)