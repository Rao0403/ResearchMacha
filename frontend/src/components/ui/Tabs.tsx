import { type KeyboardEvent, type ReactNode, useId, useRef } from "react";

export interface TabItem {
  id: string;
  label: string;
  content: ReactNode;
}

interface TabsProps {
  label: string;
  items: TabItem[];
  value: string;
  onValueChange: (value: string) => void;
}

export function Tabs({ label, items, value, onValueChange }: TabsProps) {
  const instanceId = useId();
  const tabRefs = useRef(new Map<string, HTMLButtonElement>());

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      return;
    }
    event.preventDefault();
    let nextIndex = index;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + items.length) % items.length;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % items.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = items.length - 1;
    const next = items[nextIndex];
    if (next) {
      onValueChange(next.id);
      tabRefs.current.get(next.id)?.focus();
    }
  }

  const selected = items.find((item) => item.id === value) ?? items[0];
  if (!selected) return null;

  return (
    <div className="ui-tabs">
      <div className="ui-tab-list" role="tablist" aria-label={label}>
        {items.map((item, index) => {
          const selectedItem = item.id === selected.id;
          const tabId = `${instanceId}-tab-${item.id}`;
          const panelId = `${instanceId}-panel-${item.id}`;
          return (
            <button
              key={item.id}
              ref={(node) => {
                if (node) tabRefs.current.set(item.id, node);
                else tabRefs.current.delete(item.id);
              }}
              id={tabId}
              className="ui-tab"
              type="button"
              role="tab"
              aria-selected={selectedItem}
              aria-controls={panelId}
              tabIndex={selectedItem ? 0 : -1}
              onClick={() => onValueChange(item.id)}
              onKeyDown={(event) => handleKeyDown(event, index)}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      <div
        id={`${instanceId}-panel-${selected.id}`}
        role="tabpanel"
        aria-labelledby={`${instanceId}-tab-${selected.id}`}
      >
        {selected.content}
      </div>
    </div>
  );
}
