import { useState, useRef, useEffect, useId } from 'react';
import { createPortal } from 'react-dom';
import './Citation.css';

const POPOVER_WIDTH = 300;
const POPOVER_MARGIN = 16;

interface CitationProps {
  id: string | number;
  sourceName: string;
  snippet: string;
}

export function Citation({ id, sourceName, snippet }: CitationProps) {
  const [isHovered, setIsHovered] = useState(false);
  const [placement, setPlacement] = useState<'top' | 'bottom'>('top');
  const [popoverStyle, setPopoverStyle] = useState<React.CSSProperties>({});

  const triggerRef = useRef<HTMLSpanElement>(null);
  const timeoutRef = useRef<number | undefined>(undefined);
  const instanceId = useId();

  useEffect(() => {
    const handleGlobalAction = (e: Event) => {
      if (e.type === 'citation-open') {
        const customEvent = e as CustomEvent;
        if (customEvent.detail === instanceId) return;
      }

      if (e.type === 'scroll' && triggerRef.current) {
        triggerRef.current.style.pointerEvents = 'none';
        setTimeout(() => {
          if (triggerRef.current) triggerRef.current.style.pointerEvents = '';
        }, 150);
      }

      clearTimeout(timeoutRef.current);
      setIsHovered(false);
    };

    window.addEventListener('citation-open', handleGlobalAction);
    window.addEventListener('resize', handleGlobalAction);
    window.addEventListener('scroll', handleGlobalAction, { capture: true, passive: true });

    return () => {
      window.removeEventListener('citation-open', handleGlobalAction);
      window.removeEventListener('resize', handleGlobalAction);
      window.removeEventListener('scroll', handleGlobalAction, { capture: true });
      clearTimeout(timeoutRef.current);
    };
  }, [instanceId]);

  const handleMouseEnter = () => {
    clearTimeout(timeoutRef.current);

    if (isHovered) return;

    timeoutRef.current = window.setTimeout(() => {
      window.dispatchEvent(new CustomEvent('citation-open', { detail: instanceId }));

      if (triggerRef.current) {
        const rect = triggerRef.current.getBoundingClientRect();
        const isTop = rect.top < 250;
        const safeHalfWidth = POPOVER_WIDTH / 2;
        let centerX = rect.left + rect.width / 2;

        if (centerX - safeHalfWidth < POPOVER_MARGIN) {
          centerX = safeHalfWidth + POPOVER_MARGIN;
        } else if (centerX + safeHalfWidth > window.innerWidth - POPOVER_MARGIN) {
          centerX = window.innerWidth - safeHalfWidth - POPOVER_MARGIN;
        }

        setPlacement(isTop ? 'bottom' : 'top');
        setPopoverStyle({
          left: `${centerX}px`,
          top: isTop ? `${rect.bottom + 8}px` : undefined,
          bottom: !isTop ? `${window.innerHeight - rect.top + 8}px` : undefined,
        });
      }

      setIsHovered(true);
    }, 200);
  };

  const handleMouseLeave = () => {
    clearTimeout(timeoutRef.current);
    timeoutRef.current = window.setTimeout(() => setIsHovered(false), 300);
  };

  return (
    <span
      className="citation-wrapper"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      ref={triggerRef}
    >
      <span className="citation-badge">[{id}]</span>

      {isHovered &&
        createPortal(
          <span
            className={`citation-popover citation-popover-${placement}`}
            style={popoverStyle}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
          >
            <span className="citation-popover-source">{sourceName}</span>
            <span className="citation-popover-snippet">"{snippet}"</span>
          </span>,
          document.body
        )}
    </span>
  );
}
