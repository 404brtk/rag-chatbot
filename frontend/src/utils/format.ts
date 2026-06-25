const PROVIDER_NAMES: Record<string, string> = {
  openai: 'OpenAI',
  llamacpp: 'llama.cpp',
  openrouter: 'OpenRouter',
  gemini: 'Gemini',
};

export function formatProviderName(provider: string): string {
  return PROVIDER_NAMES[provider.toLowerCase()] || provider;
}

export function formatCapitalized(val: string): string {
  if (!val) return '';
  return val.charAt(0).toUpperCase() + val.slice(1);
}
