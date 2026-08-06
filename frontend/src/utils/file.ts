export const MAX_ATTACHMENT_SIZE_BYTES = 5 * 1024 * 1024; // 5 MB

export const ACCEPTED_DOCUMENT_EXTENSIONS = [
  '.pdf',
  '.txt',
  '.md',
  '.markdown',
  '.docx',
  '.doc',
  '.pptx',
  '.ppt',
  '.xlsx',
  '.xls',
  '.csv',
  '.rtf',
  '.epub',
  '.odt',
  '.ods',
  '.odp',
];

export const ACCEPTED_CODE_EXTENSIONS = [
  '.json',
  '.js',
  '.ts',
  '.tsx',
  '.jsx',
  '.py',
  '.html',
  '.css',
  '.rs',
  '.go',
  '.c',
  '.cpp',
  '.h',
  '.sh',
  '.yml',
  '.yaml',
  '.xml',
  '.ini',
  '.conf',
  '.env',
  '.sql',
];

export const ACCEPTED_TEXT_EXTENSIONS = [
  ...ACCEPTED_DOCUMENT_EXTENSIONS,
  ...ACCEPTED_CODE_EXTENSIONS,
];

export const ACCEPTED_IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.webp'];

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  const kb = size / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

export function extensionOf(fileName: string): string {
  const parts = fileName.toLowerCase().split('.');
  if (parts.length < 2) return '';
  return `.${parts[parts.length - 1]}`;
}

export function fileNameParts(fileName: string): { baseName: string; extension: string } {
  const dotIndex = fileName.lastIndexOf('.');
  if (dotIndex <= 0 || dotIndex === fileName.length - 1) {
    return { baseName: fileName, extension: '' };
  }

  return {
    baseName: fileName.slice(0, dotIndex),
    extension: fileName.slice(dotIndex),
  };
}

export function isAllowedTextFile(file: File): boolean {
  const extension = extensionOf(file.name);
  if (extension !== '') {
    return ACCEPTED_TEXT_EXTENSIONS.includes(extension);
  }
  return file.type.startsWith('text/') || file.type === 'application/json';
}

export function isAllowedImageFile(file: File): boolean {
  const extension = extensionOf(file.name);
  if (extension !== '') {
    return ACCEPTED_IMAGE_EXTENSIONS.includes(extension);
  }
  return file.type.startsWith('image/');
}
