# Reason out Your Layout: Evoking the Layout Master from Large Language Models for Text-to-Image Synthesis

## Overview

This code repository accompanies the paper "[**Reason out Your Layout: Evoking the Layout Master from Large Language Models for Text-to-Image Synthesis.**](https://arxiv.org/abs/2311.17126)" The paper introduces a novel approach to enhance text-to-image (T2I) generative models by using Large Language Models (LLMs) as layout generators and an adapter module for integrating layout into image synthesis. 

![](https://github.com/Xiaohui9607/LLM_layout_generator/blob/main/assets/pre_vis.png)


## Requirements

We provide a modified source code of diffusers in the repository.

```
pip install --upgrade transformers scipy
```

## Download LACA/LASA

Model checkpoints can be downloaded at [https://huggingface.co/xchen16/LACA](https://huggingface.co/xchen16/LACA/tree/main)

## Inference
### step 1
Obtain the bounding boxes response from [ChatGPT](https://chat.openai.com), and save it to llm_response.txt. Two versions of the prompts are provided in the _prompts_ folders. Make sure your response format strictly follows the example below:

```
Caption: A dog stands and four balloons are in the air.

[chat gpt reasoning, will be ignored during parsing]

### Answer

- object 0: A dog [(136, 204, 376, 460)]
- object 1: Four balloons [(51, 51, 102, 102), (409, 51, 460, 102), (255, 0, 306, 51), (306, 102, 357, 153)]
- ...
```

### step 2
Run the generation script

```
python generate.py --controlnet_path ./checkpoint/laca_800000 --response_file ./llm_response.txt --g1 5.5 --g2 5.5 --tau 0.2
```
