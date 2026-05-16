'use client';

import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import { javascript } from '@codemirror/lang-javascript';
import { java } from '@codemirror/lang-java';
import { cpp } from '@codemirror/lang-cpp';
import { rust } from '@codemirror/lang-rust';
import { go } from '@codemirror/lang-go';
import { php } from '@codemirror/lang-php';
import { oneDark } from '@codemirror/theme-one-dark';
import { useTheme } from 'next-themes';
import { useMemo } from 'react';
import type { Extension } from '@codemirror/state';

type CodeEditorProps = {
  value: string;
  onChange: (value: string) => void;
  language?: string;
  placeholder?: string;
  minHeight?: string;
  maxHeight?: string;
  className?: string;
};

const languageMap: Record<string, () => Extension> = {
  python: python,
  javascript: javascript,
  typescript: javascript,
  js: javascript,
  jsx: javascript,
  java: java,
  cpp: cpp,
  'c++': cpp,
  c: cpp,
  'c#': cpp,
  csharp: cpp,
  rust: rust,
  go: go,
  golang: go,
  php: php,
};

function getLanguageExtension(languageName?: string): Extension[] {
  if (!languageName) return [];
  const normalized = languageName.toLowerCase().trim();
  const lang = languageMap[normalized];
  return lang ? [lang()] : [];
}

export function CodeEditor({
  value,
  onChange,
  language,
  placeholder = 'Enter your code here...',
  minHeight = '300px',
  maxHeight = '600px',
  className = '',
}: CodeEditorProps) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';

  const extensions = useMemo(() => getLanguageExtension(language), [language]);

  return (
    <div
      className={`bg-background relative overflow-hidden rounded-md border ${className}`}
      style={{ minHeight, maxHeight }}
    >
      <CodeMirror
        value={value}
        height={maxHeight}
        minHeight={minHeight}
        maxHeight={maxHeight}
        theme={isDark ? oneDark : undefined}
        extensions={extensions}
        onChange={onChange}
        placeholder={placeholder}
        basicSetup={{
          lineNumbers: true,
          foldGutter: true,
          dropCursor: false,
          allowMultipleSelections: false,
          indentOnInput: true,
          bracketMatching: true,
          closeBrackets: true,
          autocompletion: true,
          highlightSelectionMatches: true,
          tabSize: 2,
        }}
        className="font-mono text-sm [&_.cm-editor]:h-full [&_.cm-editor]:outline-none [&_.cm-scroller]:h-full [&_.cm-scroller]:overflow-auto"
      />
    </div>
  );
}
