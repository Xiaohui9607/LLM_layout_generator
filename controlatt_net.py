from typing import Optional
import torch
from torch import nn

from diffusers.configuration_utils import ConfigMixin
from diffusers.loaders import FromOriginalControlnetMixin
from diffusers.utils import logging
from diffusers.models.modeling_utils import ModelMixin

from diffusers.models.attention import AdaLayerNorm, BasicTransformerBlock
from diffusers.models.attention_processor import Attention


logger = logging.get_logger(__name__)  # pylint: disable=invalid-name


class CrossAttnCopy(ModelMixin, ConfigMixin, FromOriginalControlnetMixin):
    def __init__(self,
        dim: int,
        num_attention_heads: int,
        attention_head_dim: int,
        cross_attention_dim: int,
        dropout=0.0,
        num_embeds_ada_norm: Optional[int] = None,
        attention_bias: bool = False,
        upcast_attention: bool = False,
        norm_type: str = "layer_norm",
        norm_elementwise_affine: bool = True,
        user_zero: bool = True):
        super().__init__()
        self.use_ada_layer_norm_zero = (num_embeds_ada_norm is not None) and norm_type == "ada_norm_zero"
        self.use_ada_layer_norm = (num_embeds_ada_norm is not None) and norm_type == "ada_norm"
        self.user_zero = user_zero
        self.norm = (
            AdaLayerNorm(dim, num_embeds_ada_norm)
            if self.use_ada_layer_norm
            else nn.LayerNorm(dim, elementwise_affine=norm_elementwise_affine)
        )
        self.attn = Attention(
            query_dim=dim,
            cross_attention_dim=cross_attention_dim,
            heads=num_attention_heads,
            dim_head=attention_head_dim,
            dropout=dropout,
            bias=attention_bias,
            upcast_attention=upcast_attention,
        ) 
        self.conv_block = zero_module(nn.Conv2d(self.attn.inner_dim, self.attn.inner_dim, kernel_size=1))

    def forward(self,
        hidden_states: torch.FloatTensor,
        encoder_hidden_states: Optional[torch.FloatTensor] = None,
        encoder_attention_mask: Optional[torch.FloatTensor] = None,
        timestep: Optional[torch.LongTensor] = None,
        cross_attention_mask: Optional[torch.FloatTensor] = None,
        layout_hidden_states: Optional[torch.FloatTensor] = None,
        **kwargs):

        encoder_attention_mask = encoder_attention_mask if cross_attention_mask is None else cross_attention_mask
        perform_mask = (encoder_attention_mask.float().mean([1,2])!=1).half()
        encoder_hidden_states = encoder_hidden_states if layout_hidden_states is None else layout_hidden_states
        norm_hidden_states = self.norm(hidden_states, timestep) if self.use_ada_layer_norm else self.norm(hidden_states)
        if encoder_attention_mask is not None:
            b, w_h, l = encoder_attention_mask.shape
            if w_h != norm_hidden_states.shape[1]:
                scale = int((w_h // norm_hidden_states.shape[1])**0.5)
                w = h = int(w_h**0.5)
                encoder_attention_mask = encoder_attention_mask.view(b, w, h, l)
                encoder_attention_mask = encoder_attention_mask[:, ::scale, ::scale, :].reshape(b, -1, l)
        # encoder_attention_masks = encoder_attention_masks.view(b, l, w*h).bool().permute([0,2,1])
        attn_output = self.attn(
            norm_hidden_states,
            encoder_hidden_states=encoder_hidden_states,
            attention_mask=encoder_attention_mask,
        )
        batch_size, height_width, channel = attn_output.shape
        height = width = int(height_width ** 0.5)
        attn_output = self.conv_block(attn_output.permute([0,2,1])\
            .view(batch_size, channel, height, width))\
            .view(batch_size,channel,-1)\
            .permute([0,2,1]) * perform_mask[:, None, None]

        hidden_states = hidden_states + attn_output
        return hidden_states

class AttnCopy(ModelMixin, ConfigMixin, FromOriginalControlnetMixin):
    def __init__(self,
        dim: int,
        num_attention_heads: int,
        attention_head_dim: int,
        dropout=0.0,
        num_embeds_ada_norm: Optional[int] = None,
        attention_bias: bool = False,
        upcast_attention: bool = False,
        norm_type: str = "layer_norm",
        norm_elementwise_affine: bool = True,
        user_zero: bool = True):
        super().__init__()
        self.use_ada_layer_norm_zero = (num_embeds_ada_norm is not None) and norm_type == "ada_norm_zero"
        self.use_ada_layer_norm = (num_embeds_ada_norm is not None) and norm_type == "ada_norm"
        self.user_zero = user_zero
        self.norm = (
            AdaLayerNorm(dim, num_embeds_ada_norm)
            if self.use_ada_layer_norm
            else nn.LayerNorm(dim, elementwise_affine=norm_elementwise_affine)
        )
        self.attn = Attention(
            query_dim=dim,
            heads=num_attention_heads,
            dim_head=attention_head_dim,
            dropout=dropout,
            bias=attention_bias,
            upcast_attention=upcast_attention,
        ) 
        self.conv_block = zero_module(nn.Conv2d(self.attn.inner_dim, self.attn.inner_dim, kernel_size=1))

    def forward(self,
        hidden_states: torch.FloatTensor,
        timestep: Optional[torch.LongTensor] = None,
        self_attention_masks: Optional[torch.FloatTensor] = None,
        **kwargs):
        norm_hidden_states = self.norm(hidden_states, timestep) if self.use_ada_layer_norm else self.norm(hidden_states)
        if self_attention_masks is not None:
            
            perform_mask = (self_attention_masks.float().mean([1,2])!=1).half()
            b, w_h, w_h = self_attention_masks.shape
            l = norm_hidden_states.shape[1]
            if w_h != l:
                scale = int((w_h // norm_hidden_states.shape[1])**0.5)
                w = h = int(w_h**0.5)
                self_attention_masks = self_attention_masks.view(b, w, h, w, h)
                self_attention_masks = self_attention_masks[:, ::scale, ::scale, ::scale, ::scale].reshape(b, l, l)

        attn_output = self.attn(
            norm_hidden_states,
            attention_mask=self_attention_masks,
        )
        batch_size, height_width, channel = attn_output.shape
        height = width = int(height_width ** 0.5)
        attn_output = self.conv_block(attn_output.permute([0,2,1])\
            .view(batch_size, channel, height, width))\
            .view(batch_size,channel,-1)\
            .permute([0,2,1]) * perform_mask[:, None, None]

        hidden_states = hidden_states + attn_output
        return hidden_states

class CSLayoutInjectionLayers(nn.Module):
    def __init__(self, unet, add_self_att=True, copy_from_unet=True, use_zero=True): 
        super().__init__()
        if unet.encoder_hid_proj is not None:
            self.encoder_hid_proj = nn.Linear(unet.encoder_hid_proj.in_features, unet.encoder_hid_proj.out_features)
        else:
            self.encoder_hid_proj = None

        self.add_self_att = add_self_att
        self.CrossAttentionCopys = nn.ModuleList()
        self.SelfAttentionCopys = nn.ModuleList()
        for module in unet.down_blocks.modules():
            if isinstance(module, BasicTransformerBlock):
                if self.add_self_att:
                    self_additional_block = AttnCopy( 
                        dim=module.dim,
                        num_attention_heads=module.num_attention_heads,
                        attention_head_dim=module.attention_head_dim,
                        dropout=module.dropout,
                        num_embeds_ada_norm=module.num_embeds_ada_norm,
                        attention_bias=module.attention_bias,
                        upcast_attention=module.upcast_attention,
                        norm_type=module.norm_type,
                        norm_elementwise_affine=module.norm_elementwise_affine,
                        user_zero=use_zero)
                    if copy_from_unet:
                        self_additional_block.attn = copy_module(module.attn1, self_additional_block.attn)
                        self_additional_block.norm = copy_module(module.norm1, self_additional_block.norm)
                else:
                    self_additional_block = nn.Identity()
                if module.norm2 is not None and module.attn2 is not None:
                    cross_addtional_block = CrossAttnCopy( 
                        dim=module.dim,
                        num_attention_heads=module.num_attention_heads,
                        attention_head_dim=module.attention_head_dim,
                        cross_attention_dim=module.cross_attention_dim,
                        dropout=module.dropout,
                        num_embeds_ada_norm=module.num_embeds_ada_norm,
                        attention_bias=module.attention_bias,
                        upcast_attention=module.upcast_attention,
                        norm_type=module.norm_type,
                        norm_elementwise_affine=module.norm_elementwise_affine,
                        user_zero=use_zero)
                    if copy_from_unet:
                        cross_addtional_block.attn = copy_module(module.attn2, cross_addtional_block.attn)
                        cross_addtional_block.norm = copy_module(module.norm2, cross_addtional_block.norm)
                else:
                    cross_addtional_block = nn.Identity()

                self.SelfAttentionCopys.append(self_additional_block)
                self.CrossAttentionCopys.append(cross_addtional_block)

        for module in unet.mid_block.modules():
            if isinstance(module, BasicTransformerBlock):
                if self.add_self_att:
                    self_additional_block = AttnCopy( 
                        dim=module.dim,
                        num_attention_heads=module.num_attention_heads,
                        attention_head_dim=module.attention_head_dim,
                        dropout=module.dropout,
                        num_embeds_ada_norm=module.num_embeds_ada_norm,
                        attention_bias=module.attention_bias,
                        upcast_attention=module.upcast_attention,
                        norm_type=module.norm_type,
                        norm_elementwise_affine=module.norm_elementwise_affine,
                        user_zero=use_zero)
                    if copy_from_unet:
                        self_additional_block.attn = copy_module(module.attn1, self_additional_block.attn)
                        self_additional_block.norm = copy_module(module.norm1, self_additional_block.norm)
                else:
                    self_additional_block = nn.Identity()
                if module.norm2 is not None and module.attn2 is not None:
                    cross_addtional_block = CrossAttnCopy( 
                        dim=module.dim,
                        num_attention_heads=module.num_attention_heads,
                        attention_head_dim=module.attention_head_dim,
                        cross_attention_dim=module.cross_attention_dim,
                        dropout=module.dropout,
                        num_embeds_ada_norm=module.num_embeds_ada_norm,
                        attention_bias=module.attention_bias,
                        upcast_attention=module.upcast_attention,
                        norm_type=module.norm_type,
                        norm_elementwise_affine=module.norm_elementwise_affine,
                        user_zero=use_zero)
                    if copy_from_unet:
                        cross_addtional_block.attn = copy_module(module.attn2, cross_addtional_block.attn)
                        cross_addtional_block.norm = copy_module(module.norm2, cross_addtional_block.norm)
                else:
                    cross_addtional_block = nn.Identity()

                self.SelfAttentionCopys.append(self_additional_block)
                self.CrossAttentionCopys.append(cross_addtional_block)

        for module in unet.up_blocks.modules():
            if isinstance(module, BasicTransformerBlock):

                if self.add_self_att:
                    self_additional_block = AttnCopy( 
                        dim=module.dim,
                        num_attention_heads=module.num_attention_heads,
                        attention_head_dim=module.attention_head_dim,
                        dropout=module.dropout,
                        num_embeds_ada_norm=module.num_embeds_ada_norm,
                        attention_bias=module.attention_bias,
                        upcast_attention=module.upcast_attention,
                        norm_type=module.norm_type,
                        norm_elementwise_affine=module.norm_elementwise_affine,
                        user_zero=use_zero)
                    if copy_from_unet:
                        self_additional_block.attn = copy_module(module.attn1, self_additional_block.attn)
                        self_additional_block.norm = copy_module(module.norm1, self_additional_block.norm)
                else:
                    self_additional_block = nn.Identity()

                if module.norm2 is not None and module.attn2 is not None:
                    cross_addtional_block = CrossAttnCopy( 
                        dim=module.dim,
                        num_attention_heads=module.num_attention_heads,
                        attention_head_dim=module.attention_head_dim,
                        cross_attention_dim=module.cross_attention_dim,
                        dropout=module.dropout,
                        num_embeds_ada_norm=module.num_embeds_ada_norm,
                        attention_bias=module.attention_bias,
                        upcast_attention=module.upcast_attention,
                        norm_type=module.norm_type,
                        norm_elementwise_affine=module.norm_elementwise_affine,
                        user_zero=use_zero)
                    if copy_from_unet:
                        cross_addtional_block.attn = copy_module(module.attn2, cross_addtional_block.attn)
                        cross_addtional_block.norm = copy_module(module.norm2, cross_addtional_block.norm)
                else:
                    cross_addtional_block = nn.Identity()

                self.SelfAttentionCopys.append(self_additional_block)
                self.CrossAttentionCopys.append(cross_addtional_block)

    def forward(self, encoder_hidden_states=None, cross_attention_masks=None, self_attention_masks=None):
        if encoder_hidden_states is not None:
            if self.encoder_hid_proj:
                encoder_hidden_states = self.encoder_hid_proj(encoder_hidden_states)
        attn_outputs = []
        cross_attention_masks = cross_attention_masks

        for self_att_module, cross_att_module in zip(self.SelfAttentionCopys, self.CrossAttentionCopys):
            attn_outputs.append({
                'self_layer': self_att_module, 
                'cross_layer': cross_att_module,
                'x': {
                    'layout_hidden_states': encoder_hidden_states, 
                    'cross_attention_mask': cross_attention_masks,
                    'self_attention_masks': self_attention_masks}})
        return {'attn': attn_outputs}

class CLayoutInjectionLayers(nn.Module):
    def __init__(self, unet, copy_from_unet=True, use_zero=True): 
        super().__init__()
        if unet.encoder_hid_proj is not None:
            self.encoder_hid_proj = nn.Linear(unet.encoder_hid_proj.in_features, unet.encoder_hid_proj.out_features)
            # load unet model weight
        else:
            self.encoder_hid_proj = None
        self.AttentionCopys = nn.ModuleList()
        for module in unet.down_blocks.modules():
            if isinstance(module, BasicTransformerBlock):
                if module.norm2 is not None and module.attn2 is not None:
                    addtional_block = CrossAttnCopy( 
                        dim=module.dim,
                        num_attention_heads=module.num_attention_heads,
                        attention_head_dim=module.attention_head_dim,
                        cross_attention_dim=module.cross_attention_dim,
                        dropout=module.dropout,
                        num_embeds_ada_norm=module.num_embeds_ada_norm,
                        attention_bias=module.attention_bias,
                        upcast_attention=module.upcast_attention,
                        norm_type=module.norm_type,
                        norm_elementwise_affine=module.norm_elementwise_affine,
                        user_zero=use_zero)
                    if copy_from_unet:
                        addtional_block.attn = copy_module(module.attn2, addtional_block.attn)
                        addtional_block.norm = copy_module(module.norm2, addtional_block.norm)
                else:
                    addtional_block = nn.Identity()
                self.AttentionCopys.append(addtional_block)
        
        for module in unet.mid_block.modules():
            if isinstance(module, BasicTransformerBlock):
                if module.norm2 is not None and module.attn2 is not None:
                    addtional_block = CrossAttnCopy( 
                        dim=module.dim,
                        num_attention_heads=module.num_attention_heads,
                        attention_head_dim=module.attention_head_dim,
                        cross_attention_dim=module.cross_attention_dim,
                        dropout=module.dropout,
                        num_embeds_ada_norm=module.num_embeds_ada_norm,
                        attention_bias=module.attention_bias,
                        upcast_attention=module.upcast_attention,
                        norm_type=module.norm_type,
                        norm_elementwise_affine=module.norm_elementwise_affine,
                        user_zero=use_zero)
                    if copy_from_unet:
                        addtional_block.attn = copy_module(module.attn2, addtional_block.attn)
                        addtional_block.norm = copy_module(module.norm2, addtional_block.norm)
                    
                else:
                    addtional_block = nn.Identity()
                self.AttentionCopys.append(addtional_block)
        
        for module in unet.up_blocks.modules():
            if isinstance(module, BasicTransformerBlock):
                if module.norm2 is not None and module.attn2 is not None:
                    addtional_block = CrossAttnCopy( 
                        dim=module.dim,
                        num_attention_heads=module.num_attention_heads,
                        attention_head_dim=module.attention_head_dim,
                        cross_attention_dim=module.cross_attention_dim,
                        dropout=module.dropout,
                        num_embeds_ada_norm=module.num_embeds_ada_norm,
                        attention_bias=module.attention_bias,
                        upcast_attention=module.upcast_attention,
                        norm_type=module.norm_type,
                        norm_elementwise_affine=module.norm_elementwise_affine,
                        user_zero=use_zero)
                    if copy_from_unet:
                        addtional_block.attn = copy_module(module.attn2, addtional_block.attn)
                        addtional_block.norm = copy_module(module.norm2, addtional_block.norm)
                    
                else:
                    addtional_block = nn.Identity()
                self.AttentionCopys.append(addtional_block)
        
    def forward(self, encoder_hidden_states=None, cross_attention_masks=None, **kwargs):
        if encoder_hidden_states is not None:
            if self.encoder_hid_proj:
                encoder_hidden_states = self.encoder_hid_proj(encoder_hidden_states)
        attn_outputs = []
        for module in self.AttentionCopys:
            attn_outputs.append({
                'cross_layer': module, 
                'x': {
                    'layout_hidden_states': encoder_hidden_states, 
                    'cross_attention_mask': cross_attention_masks}}
                                )
        return {'attn': attn_outputs}

def copy_module(from_module, to_module):
    for pfrom, pto in zip(from_module.parameters(), to_module.parameters()):
        with torch.no_grad():
            pto.copy_(pfrom)
    return to_module

def zero_module(module):
    for p in module.parameters():
        nn.init.zeros_(p)
    return module
