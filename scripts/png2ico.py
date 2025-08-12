from PIL import Image
import os
import argparse

def convert_to_ico(input_file, output_file=None, sizes=None):
    """
    Convert PNG to ICO with customizable options
    
    :param input_file: Path to input PNG file
    :param output_file: Path to output ICO file (optional)
    :param sizes: List of sizes to include in the ICO (optional)
    """
    # Default sizes if not specified
    if sizes is None:
        sizes = [(16,16), (32,32), (48,48), (64,64), (128,128)]
    
    # If no output file specified, use input filename with .ico extension
    if output_file is None:
        output_file = os.path.splitext(input_file)[0] + '.ico'
    
    try:
        # Open the image
        img = Image.open(input_file)
        
        # Ensure image is in RGBA mode
        img = img.convert("RGBA")
        
        # Save as ICO with multiple sizes
        img.save(output_file, format='ICO', sizes=sizes)
        
        print(f"Successfully converted {input_file} to {output_file}")
        print(f"Included sizes: {sizes}")
    
    except Exception as e:
        print(f"Error converting image: {e}")

def main():
    parser = argparse.ArgumentParser(description='Convert PNG to ICO')
    parser.add_argument('input', help='Input PNG file')
    parser.add_argument('-o', '--output', help='Output ICO file (optional)')
    parser.add_argument('-s', '--sizes', nargs='+', type=int, 
                        help='Sizes to include (e.g., -s 16 32 48 64 128)')
    
    args = parser.parse_args()
    
    # Prepare sizes if specified
    sizes = None
    if args.sizes:
        # Create size tuples from input
        sizes = [(size, size) for size in args.sizes]
    
    # Convert the image
    convert_to_ico(args.input, args.output, sizes)

if __name__ == '__main__':
    main()
