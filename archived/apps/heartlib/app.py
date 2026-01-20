"""
HeartLib Gradio Web Interface
Music generation using HeartMuLa foundation models
"""

import os
import gradio as gr
import torch
import tempfile
from pathlib import Path

# Model paths - mounted via NFS
MODEL_PATH = os.environ.get("MODEL_PATH", "/models")
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "/output")

# Check if models are available
def check_models():
    """Check if required model files exist"""
    required = ["HeartCodec-oss", "HeartMuLa-oss-3B", "gen_config.json", "tokenizer.json"]
    missing = []
    for item in required:
        if not Path(MODEL_PATH, item).exists():
            missing.append(item)
    return missing

def generate_music(lyrics: str, tags: str, max_length_sec: int, temperature: float, topk: int, cfg_scale: float):
    """Generate music from lyrics and tags"""
    try:
        # Check for models
        missing = check_models()
        if missing:
            return None, f"Missing model files: {', '.join(missing)}. Please download models to {MODEL_PATH}"
        
        # Import here to avoid startup errors if models missing
        from heartlib.generation import HeartMuLaGenerator
        
        # Initialize generator
        generator = HeartMuLaGenerator(
            model_path=MODEL_PATH,
            version="3B"
        )
        
        # Create temp files for input
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as lyrics_file:
            lyrics_file.write(lyrics)
            lyrics_path = lyrics_file.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tags_file:
            tags_file.write(tags)
            tags_path = tags_file.name
        
        # Generate output path
        output_file = os.path.join(OUTPUT_PATH, "generated_music.mp3")
        
        # Generate music
        generator.generate(
            lyrics_path=lyrics_path,
            tags_path=tags_path,
            save_path=output_file,
            max_audio_length_ms=max_length_sec * 1000,
            temperature=temperature,
            topk=topk,
            cfg_scale=cfg_scale
        )
        
        # Cleanup temp files
        os.unlink(lyrics_path)
        os.unlink(tags_path)
        
        return output_file, "Music generated successfully!"
        
    except Exception as e:
        return None, f"Error generating music: {str(e)}"

def get_status():
    """Get current system status"""
    status = []
    
    # Check GPU
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        status.append(f"✅ GPU: {gpu_name} ({gpu_memory:.1f} GB)")
    else:
        status.append("❌ GPU: Not available")
    
    # Check models
    missing = check_models()
    if not missing:
        status.append("✅ Models: All loaded")
    else:
        status.append(f"⚠️ Models: Missing {len(missing)} files")
    
    return "\n".join(status)

# Example lyrics
EXAMPLE_LYRICS = """[Intro]
[Verse]
The sun creeps in across the floor
I hear the traffic outside the door
The coffee pot begins to hiss
It is another morning just like this
[Chorus]
Every day the light returns
Every day the fire burns
We keep on walking down this street
Moving to the same steady beat
[Outro]
Just another day"""

EXAMPLE_TAGS = "piano,happy,upbeat,pop,synthesizer"

# Build Gradio interface
with gr.Blocks(title="HeartLib - Music Generation", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🎵 HeartLib Music Generator
    Generate music from lyrics and tags using the HeartMuLa foundation model.
    """)
    
    with gr.Row():
        with gr.Column():
            gr.Markdown("### System Status")
            status_text = gr.Textbox(value=get_status(), label="", interactive=False, lines=3)
            refresh_btn = gr.Button("🔄 Refresh Status", size="sm")
            refresh_btn.click(fn=get_status, outputs=status_text)
    
    with gr.Row():
        with gr.Column(scale=2):
            lyrics_input = gr.Textbox(
                label="Lyrics",
                placeholder="Enter lyrics with sections like [Verse], [Chorus], etc.",
                lines=12,
                value=EXAMPLE_LYRICS
            )
            tags_input = gr.Textbox(
                label="Tags (comma-separated)",
                placeholder="piano,happy,pop",
                value=EXAMPLE_TAGS
            )
        
        with gr.Column(scale=1):
            max_length = gr.Slider(
                minimum=30,
                maximum=240,
                value=120,
                step=10,
                label="Max Length (seconds)"
            )
            temperature = gr.Slider(
                minimum=0.1,
                maximum=2.0,
                value=1.0,
                step=0.1,
                label="Temperature"
            )
            topk = gr.Slider(
                minimum=10,
                maximum=100,
                value=50,
                step=5,
                label="Top-K Sampling"
            )
            cfg_scale = gr.Slider(
                minimum=1.0,
                maximum=3.0,
                value=1.5,
                step=0.1,
                label="CFG Scale"
            )
    
    generate_btn = gr.Button("🎼 Generate Music", variant="primary", size="lg")
    
    with gr.Row():
        audio_output = gr.Audio(label="Generated Music", type="filepath")
        status_output = gr.Textbox(label="Status", lines=2)
    
    generate_btn.click(
        fn=generate_music,
        inputs=[lyrics_input, tags_input, max_length, temperature, topk, cfg_scale],
        outputs=[audio_output, status_output]
    )
    
    gr.Markdown("""
    ---
    **Note**: First generation may take longer as models are loaded into GPU memory.
    
    Models should be downloaded to the `/models` directory. See [HeartMuLa documentation](https://github.com/HeartMuLa/heartlib) for download instructions.
    """)

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False
    )
