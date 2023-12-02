# Reason out Your Layout: Evoking the Layout Master from Large Language Models for Text-to-Image Synthesis

## Overview

This code repository accompanies the paper "Reason out Your Layout: Evoking the Layout Master from Large Language Models for Text-to-Image Synthesis." The paper introduces a novel approach to enhance text-to-image (T2I) generative models by using Large Language Models (LLMs) as layout generators and an adapter module for integrating layout into image synthesis. 

![Alt text](https://github.com/Xiaohui9607/LLM_layout_generator/assets/pre_vis.pdf)


### Code Structure

- **Adapter Module**: Contains the implementation of the Layout-Aware Cross-Attention (LACA) adapter, which is central to integrating layout information into the Stable Diffusion model.

- **Prompt Design**: Scripts and instructions for designing effective Chain-of-Thought (CoT) prompts to elicit detailed layout generation from LLMs.

- **Image Generation Example**: An example script demonstrating how to use the adapter module and CoT prompts to generate an image from a textual description.

### Image Demonstration

For an illustration of the method's effectiveness, refer to Figure 2 in the paper. This figure demonstrates the generation pipeline, showing how a caption is first processed by an LLM to generate an object layout, which is then used by the Stable Diffusion model, enhanced with the LACA adapter, to generate the final image【10†source】.

### Getting Started

1. **Setup**: Install necessary dependencies as listed in `requirements.txt`.

2. **Running the Adapter Module**: Use the provided script to integrate the LACA adapter with the Stable Diffusion model. Ensure the model weights are correctly loaded.

3. **Generating Layouts with LLMs**: Follow the prompt design guidelines to create CoT prompts for the LLMs. These prompts will guide the LLMs to generate detailed object layouts from textual descriptions.

4. **Image Synthesis**: Use the example script to synthesize an image from a text prompt. The script will utilize the generated layout and the enhanced Stable Diffusion model to produce the final image.
