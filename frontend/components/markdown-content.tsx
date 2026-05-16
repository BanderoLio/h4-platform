'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import type { ComponentPropsWithoutRef, ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { CodeBlock } from '@/components/code-block';

type MarkdownContentProps = {
  content: string;
  className?: string;
};

type MarkdownCodeProps = ComponentPropsWithoutRef<'code'> & {
  inline?: boolean;
  className?: string;
  children?: ReactNode;
};

const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-3 leading-7 last:mb-0">{children}</p>,
  h1: ({ children }) => (
    <h1 className="mb-3 text-xl leading-tight font-semibold">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-3 text-lg leading-tight font-semibold">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 text-base leading-tight font-semibold">{children}</h3>
  ),
  ul: ({ children }) => (
    <ul className="mb-3 ml-5 list-disc space-y-1 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-3 ml-5 list-decimal space-y-1 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-7">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="text-muted-foreground border-l-2 pl-3 italic">
      {children}
    </blockquote>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      className="text-primary underline underline-offset-2 hover:opacity-90"
      target="_blank"
      rel="noreferrer"
    >
      {children}
    </a>
  ),
  code: ({ inline, className, children }: MarkdownCodeProps) => {
    const codeContent = String(children).replace(/\n$/, '');
    const match = /language-(\w+)/.exec(className || '');
    const language = match?.[1];

    if (inline) {
      return (
        <code className="bg-muted rounded px-1.5 py-0.5 font-mono text-sm">
          {children}
        </code>
      );
    }

    return <CodeBlock code={codeContent} language={language} />;
  },
};

export function MarkdownContent({ content, className }: MarkdownContentProps) {
  return (
    <div className={cn('text-sm', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={markdownComponents}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
