from transformers import AutoTokenizer
import torch
import ast
from PIL import ImageDraw

def draw_box(img, boxes):
    colors = ["red", "olive", "blue", "green", "orange", "brown", "cyan", "purple"]
    draw = ImageDraw.Draw(img)
    for bid, box in enumerate(boxes):
        draw.rectangle([box[0], box[1], box[2], box[3]], outline =colors[bid % len(colors)], width=4)
    return img 

def vis_bbox(img, norm_boxes):
    W, H = img.size
    boxes = []
    for box in norm_boxes:    
        x0,y0,x1,y1 = box
        boxes.append( [float(x0*W), float(y0*H), float(x1*W), float(y1*H)] )
    img = draw_box(img, boxes)
    return img

class ResponseExtractor:
    def __init__(self):

        self.tokenizer = AutoTokenizer.from_pretrained(
            "runwayml/stable-diffusion-v1-5",
            subfolder="tokenizer",
            use_fast=True)
    def _is_overlap(self, interval1, interval2):
        return not (interval1[1] <= interval2[0] or interval2[1] <= interval1[0])

    def extract_response_to_caption(self, response):
        objects = response.split("Answer: ")[-1].split('\n')[1:]
        caption = response.split("Now let's analyze the caption step by step, identify actual objects in the description, then try to infer a plausible layout of those objects. Note that your final answer should strictly follow the format given in the example. When representing the identified objects in your answer, you should use the exact same words that appear in the caption.")[-1].strip().split('\n')[0]
        caption = caption.split('Caption: ')[1]
        return caption, objects
    
    def layout_to_attmask(self, caption, objects):
        token_length = 64
        boxes = []
        tokens_positive = []
        phrases = []
        lower_caption = caption.lower()
        for object in objects:
            object = object.lower()
            temp = object.split('- ')[-1]
            cutoff = temp.rfind('[(')
            phrase = temp[:cutoff-1]
            phrase = phrase[phrase.rfind(': ')+2:]
            try:
                box = ast.literal_eval(temp[cutoff:].strip())
                if max(box[0])<1:
                    box = [[e for e in b] for b in box]
                else:
                    box = [[e/512 for e in b] for b in box]
                token_positive = (lower_caption.find(phrase), lower_caption.find(phrase)+len(phrase))
                if token_positive[0] == -1:
                    phrase = ' '.join(phrase.split()[1:])
                    token_positive = (lower_caption.find(phrase), lower_caption.find(phrase)+len(phrase))
                if token_positive[0] == -1:
                    continue
            except:
                continue
            for b in box:
                if len(b)==4:
                    if (b[0] < b[2]) and (b[1] < b[3]):
                        boxes.append(b)
                        tokens_positive.append([token_positive])
                        phrases.append(phrase)
        if len(boxes) == 0:
            return None
        boxes = torch.tensor(boxes)
        cap_out = self.tokenizer(
                    caption, 
                    max_length=self.tokenizer.model_max_length, 
                    padding="max_length", 
                    truncation=True, 
                    return_tensors="pt",
                    return_offsets_mapping=True
                )
        token_length = 64
        offset_mapping = cap_out.offset_mapping[0]
        layout_mask = torch.zeros(self.tokenizer.model_max_length, token_length, token_length)
        unique_boxes = torch.unique(boxes, dim=0)
        object_masks = torch.zeros(unique_boxes.shape[0], token_length, token_length)
        # compose self_att mask
        for i, unique_box in enumerate(unique_boxes):
            x0, y0, x1, y1 = unique_box
            object_masks[i, int(y0*token_length):int(y1*token_length), int(x0*token_length):int(x1*token_length)] = 1
        object_masks = object_masks.view(unique_boxes.shape[0], -1)
        self_layout = torch.ones(token_length**2, token_length**2)
        for i in range(object_masks.shape[0]):
            has_obj = (object_masks[i]==1).nonzero(as_tuple=True)[0]
            m = torch.ones(token_length**2, token_length**2)
            has_obj_attmask = torch.outer(object_masks[i, has_obj],object_masks[i])
            m[has_obj] = has_obj_attmask
            all_ones_m = m.mean(1)==1
            all_ones_sm = self_layout.mean(1)==1
            sm_ones_m_zeros = all_ones_sm.logical_and(~all_ones_m).nonzero(as_tuple=True)[0]
            sm_zeros_m_zeros = (~all_ones_sm).logical_and(~all_ones_m).nonzero(as_tuple=True)[0]
            self_layout[sm_ones_m_zeros] = m[sm_ones_m_zeros]# no object is sm but object in m, set m
            self_layout[sm_zeros_m_zeros] = self_layout[sm_zeros_m_zeros].bool().logical_or(m[sm_zeros_m_zeros].bool()).float() # both objects, set sm or m
        # compose cross_att mask 
        has_object_in_token = {}
        for i_token, int1 in enumerate(offset_mapping):
            if i_token == 0 or i_token == len(offset_mapping)-1:
                continue
            has_object_in_token[i_token] = []
            for i_object, token_positive in enumerate(tokens_positive):
                for int2 in token_positive:
                    if self._is_overlap(int1, int2):
                        has_object_in_token[i_token].append(i_object)

        for i in range(self.tokenizer.model_max_length):
            if i not in has_object_in_token or len(has_object_in_token[i]) == 0:
                layout_mask[i,...] = 1
            else:
                for i_object in has_object_in_token[i]:
                    x0, y0, x1, y1 = boxes[i_object]
                    # get box 
                    layout_mask[i, int(y0*token_length):int(y1*token_length), int(x0*token_length):int(x1*token_length)] = 1
    
        return caption, boxes, phrases, self_layout, layout_mask

