import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

export type VirtualScrollProps<T> = {
  items: T[];
  getItemKey: (item: T, index: number) => string | number;
  estimateSize: number;
  overscan?: number;
  className?: string;
  innerClassName?: string;
  scrollRef?: RefObject<HTMLDivElement | null>;
  onScroll?: () => void;
  stickToBottom?: boolean;
  empty?: ReactNode;
  children: (item: T, index: number) => ReactNode;
};

export function VirtualScroll<T>({
  items,
  getItemKey,
  estimateSize,
  overscan = 12,
  className,
  innerClassName,
  scrollRef: externalScrollRef,
  onScroll,
  stickToBottom = false,
  empty,
  children,
}: VirtualScrollProps<T>) {
  const internalScrollRef = useRef<HTMLDivElement>(null);
  const scrollRef = externalScrollRef ?? internalScrollRef;

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimateSize,
    overscan,
    getItemKey: (index) => String(getItemKey(items[index], index)),
  });

  const lastCountRef = useRef(0);
  useEffect(() => {
    if (!stickToBottom || items.length === 0) return;
    if (items.length >= lastCountRef.current) {
      virtualizer.scrollToIndex(items.length - 1, { align: "end" });
    }
    lastCountRef.current = items.length;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- scroll when list grows while pinned
  }, [items.length, stickToBottom]);

  if (items.length === 0) {
    return <div className={className}>{empty}</div>;
  }

  const virtualItems = virtualizer.getVirtualItems();

  return (
    <div ref={scrollRef} onScroll={onScroll} className={className}>
      <div
        className={innerClassName}
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: "100%",
          position: "relative",
        }}
      >
        {virtualItems.map((virtualRow) => {
          const item = items[virtualRow.index];
          return (
            <div
              key={virtualRow.key}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              {children(item, virtualRow.index)}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Scroll parent + sticky header + virtual rows (CSS grid). */
export type VirtualGridProps<T> = {
  items: T[];
  getItemKey: (item: T, index: number) => string | number;
  estimateSize: number;
  gridClassName: string;
  headerClassName?: string;
  header: ReactNode;
  className?: string;
  overscan?: number;
  empty?: ReactNode;
  children: (item: T, index: number) => ReactNode;
};

export function VirtualGrid<T>({
  items,
  getItemKey,
  estimateSize,
  gridClassName,
  headerClassName,
  header,
  className,
  overscan = 10,
  empty,
  children,
}: VirtualGridProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const headerCls = headerClassName ?? gridClassName;

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimateSize,
    overscan,
    getItemKey: (index) => String(getItemKey(items[index], index)),
  });

  if (items.length === 0) {
    return (
      <div className={className}>
        <div className={`sticky top-0 z-10 bg-zinc-950/95 backdrop-blur ${headerCls}`}>
          {header}
        </div>
        {empty}
      </div>
    );
  }

  const virtualItems = virtualizer.getVirtualItems();

  return (
    <div ref={scrollRef} className={className}>
      <div className={`sticky top-0 z-10 bg-zinc-950/95 backdrop-blur ${headerCls}`}>
        {header}
      </div>
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: "100%",
          position: "relative",
        }}
      >
        {virtualItems.map((virtualRow) => {
          const item = items[virtualRow.index];
          return (
            <div
              key={virtualRow.key}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              className={gridClassName}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              {children(item, virtualRow.index)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
