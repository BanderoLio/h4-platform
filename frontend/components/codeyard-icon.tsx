import Image from 'next/image';

type CodeyarnIconProps = {
  width: number;
  height: number;
  className?: string;
};

export function CodeyardIcon({ width, height, className }: CodeyarnIconProps) {
  return (
    <Image
      src={'/codeyard.png'}
      alt="Codeyard"
      className={`aspect-square [image-rendering:pixelated] ${className || ''}`}
      width={width}
      height={height}
    />
  );
}
