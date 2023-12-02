from diffusers import  UniPCMultistepScheduler
import torch
from pipeline import StableDiffusionLayoutPipeline
from utils import ResponseExtractor, vis_bbox
import argparse

parser = argparse.ArgumentParser()

parser.add_argument('--base_model_path', default="runwayml/stable-diffusion-v1-5", type=str)
parser.add_argument('--controlnet_path', default="./checkpoints/laca_800000", type=str)
parser.add_argument('--response_file', default="./llm_response.txt", type=str)
parser.add_argument('--g1', default=5.5, type=float)
parser.add_argument('--g2', default=5.5, type=float)
parser.add_argument('--tau', default=0.2, type=float)

args = parser.parse_args()
base_model_path = args.base_model_path
controlnet_path = args.controlnet_path
response = open(args.response_file, 'r').read().strip()
generator = torch.manual_seed(42)

g1 = args.g1
g2 = args.g2
tau = args.tau

if 'laca' in controlnet_path:
    from controlatt_net import CLayoutInjectionLayers as LayoutInjectionLayers
else:#lasa+laca
    from controlatt_net import CSLayoutInjectionLayers as LayoutInjectionLayers

# prepare
pipe = StableDiffusionLayoutPipeline.from_pretrained(
    base_model_path, torch_dtype=torch.float16, safety_checker=None,
)
layoutnet = LayoutInjectionLayers(pipe.unet)
layoutnet.to(device='cuda:0', dtype=torch.float16)
state_dict = torch.load(f"{controlnet_path}/pytorch_model.bin")
layoutnet.load_state_dict(state_dict)

pipe.set_layoutnet(layoutnet)

pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)

pipe.enable_xformers_memory_efficient_attention()

pipe.enable_model_cpu_offload()

gpt_layout_generator = ResponseExtractor()

# generate
caption, objects = gpt_layout_generator.extract_response_to_caption(response)

sd_input = gpt_layout_generator.layout_to_attmask(caption, objects)
if sd_input:
    caption, boxes, phrases, self_layout, cross_layout = sd_input
    self_layout = self_layout[None, ...].int()
    cross_layout = cross_layout[None, ...].int()
    b, l, w, h = cross_layout.shape
    cross_layout = cross_layout.view(b, l, w*h).bool().permute([0,2,1])
    cross_layout = torch.cat([torch.ones_like(cross_layout), torch.ones_like(cross_layout), cross_layout],dim=0).bool()
    self_layout = torch.cat([torch.ones_like(self_layout), torch.ones_like(self_layout), self_layout],dim=0).bool()
    image = pipe(
        caption, num_inference_steps=50, generator=generator, self_layout=self_layout, cross_layout=cross_layout, guidance_scale1=g1, guidance_scale2=g2, tau=tau).images[0]
    image.save(f"image_sample.png")
    image = vis_bbox(image, boxes)
    image.save(f"image_bbox.png")
else:
    print('parse error')