'use client';

import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import {
  oneDark,
  oneLight,
} from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Copy, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useTheme } from 'next-themes';
import { useTranslations } from 'next-intl';

type CodeBlockProps = {
  code: string;
  language?: string;
  showCopyButton?: boolean;
};

const languageMap: Record<string, string> = {
  // Python
  python: 'python',
  python3: 'python',
  py: 'python',
  // JavaScript/TypeScript
  javascript: 'javascript',
  js: 'javascript',
  node: 'javascript',
  nodejs: 'javascript',
  typescript: 'typescript',
  ts: 'typescript',
  tsx: 'tsx',
  jsx: 'jsx',
  // Java/Kotlin
  java: 'java',
  kotlin: 'kotlin',
  kt: 'kotlin',
  // Swift/Objective-C
  swift: 'swift',
  objc: 'objectivec',
  objectivec: 'objectivec',
  'objective-c': 'objectivec',
  // C/C++
  cpp: 'cpp',
  'c++': 'cpp',
  c: 'c',
  cxx: 'cpp',
  // C#
  csharp: 'csharp',
  'c#': 'csharp',
  cs: 'csharp',
  // Go
  go: 'go',
  golang: 'go',
  // Rust
  rust: 'rust',
  rs: 'rust',
  // PHP
  php: 'php',
  // Ruby
  ruby: 'ruby',
  rb: 'ruby',
  // Other
  html: 'markup',
  css: 'css',
  sql: 'sql',
  bash: 'bash',
  shell: 'bash',
  sh: 'bash',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  markdown: 'markdown',
  md: 'markdown',
};

function detectLanguage(code: string, languageName?: string): string {
  // First, try to match by language name if provided
  if (languageName) {
    const normalized = languageName.toLowerCase().replace(/\s+/g, '');
    const mapped = languageMap[normalized];
    if (mapped) return mapped;
    // Try partial match for common patterns
    if (normalized.includes('python')) return 'python';
    if (normalized.includes('javascript') || normalized.includes('js'))
      return 'javascript';
    if (normalized.includes('typescript') || normalized.includes('ts'))
      return 'typescript';
    if (normalized.includes('java') && !normalized.includes('script'))
      return 'java';
    if (normalized.includes('c++') || normalized.includes('cpp')) return 'cpp';
    if (normalized.includes('c#') || normalized.includes('csharp'))
      return 'csharp';
    // Return normalized if no match found
    return normalized;
  }

  // Fallback to code analysis
  const snippet = code.trim().slice(0, 500).toLowerCase();

  // Python patterns
  if (
    snippet.includes('def ') ||
    snippet.includes('import ') ||
    snippet.includes('from ') ||
    snippet.includes('print(') ||
    snippet.includes('if __name__')
  )
    return 'python';

  // JavaScript/TypeScript patterns
  if (
    snippet.includes('console.log') ||
    snippet.includes('function ') ||
    snippet.includes('const ') ||
    snippet.includes('let ') ||
    snippet.includes('var ') ||
    snippet.includes('=>') ||
    snippet.includes('export ') ||
    snippet.includes('require(')
  )
    return 'javascript';

  // TypeScript specific
  if (snippet.includes('interface ') || snippet.includes('type '))
    return 'typescript';

  // Java patterns
  if (
    snippet.includes('public class') ||
    snippet.includes('public static void main') ||
    snippet.includes('@override') ||
    snippet.includes('package ')
  )
    return 'java';

  // C/C++ patterns
  if (
    snippet.includes('#include') ||
    snippet.includes('std::') ||
    snippet.includes('using namespace') ||
    snippet.includes('int main(')
  )
    return 'cpp';

  // C# patterns
  if (
    snippet.includes('using system') ||
    snippet.includes('namespace ') ||
    (snippet.includes('public class') && snippet.includes('{'))
  )
    return 'csharp';

  // Go patterns
  if (
    snippet.includes('package ') ||
    snippet.includes('fmt.') ||
    snippet.includes('func main()') ||
    snippet.includes('import "')
  )
    return 'go';

  // Rust patterns
  if (
    snippet.includes('fn main()') ||
    snippet.includes('println!') ||
    snippet.includes('use ') ||
    snippet.includes('let mut ')
  )
    return 'rust';

  // PHP patterns
  if (snippet.includes('<?php') || snippet.includes('<?=')) return 'php';

  // Ruby patterns
  if (
    (snippet.includes('def ') && !snippet.includes('def __')) ||
    snippet.includes('end') ||
    snippet.includes('require ')
  )
    return 'ruby';

  // HTML patterns
  if (snippet.includes('<!doctype') || snippet.includes('<html'))
    return 'markup';

  // SQL patterns
  if (
    snippet.includes('select ') ||
    snippet.includes('from ') ||
    snippet.includes('where ') ||
    snippet.includes('insert into')
  )
    return 'sql';

  // Default fallback
  return 'text';
}

export function CodeBlock({
  code,
  language,
  showCopyButton = true,
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const [mounted, setMounted] = useState(false);
  const { resolvedTheme } = useTheme();
  const t = useTranslations('CodeBlock');

  const detectedLanguage = useMemo(
    () => detectLanguage(code, language),
    [code, language],
  );

  const highlightStyle = resolvedTheme === 'dark' ? oneDark : oneLight;

  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      toast.success(t('copySuccess'));
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t('copyError'));
    }
  };

  return (
    <div
      className="bg-muted/30 relative w-full max-w-full overflow-x-auto rounded-md border p-4"
      role="region"
      aria-label="Code block"
    >
      {showCopyButton && (
        <Button
          variant="ghost"
          size="sm"
          onClick={copyToClipboard}
          className="absolute top-2 right-2 z-10 h-8 text-xs"
          aria-label={copied ? t('copiedLabel') : t('copy')}
          disabled={copied}
        >
          {copied ? (
            <>
              <Check className="mr-1 h-3 w-3" aria-hidden="true" />
              {t('copiedLabel')}
            </>
          ) : (
            <>
              <Copy className="mr-1 h-3 w-3" aria-hidden="true" />
              {t('copy')}
            </>
          )}
        </Button>
      )}
      {mounted ? (
        <div className="min-w-0 overflow-x-auto">
          <SyntaxHighlighter
            language={detectedLanguage}
            style={highlightStyle}
            customStyle={{
              margin: 0,
              borderRadius: '0.375rem',
              fontSize: '0.875rem',
              lineHeight: '1.5',
              background: 'transparent',
              minWidth: 'fit-content',
            }}
            showLineNumbers
            wrapLines
            wrapLongLines
            aria-label={`Code block in ${detectedLanguage}`}
          >
            {code}
          </SyntaxHighlighter>
        </div>
      ) : (
        <pre className="bg-muted/30 text-muted-foreground min-w-0 overflow-x-auto rounded-md border p-4 text-xs">
          {code}
        </pre>
      )}
    </div>
  );
}
