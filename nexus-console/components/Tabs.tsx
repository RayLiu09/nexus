"use client";

type Tab = {
  id: string;
  label: string;
  badge?: number | string;
  badgeTone?: "default" | "warning" | "danger";
};

type TabsProps = {
  tabs: Tab[];
  activeTab: string;
  onTabChange: (tabId: string) => void;
};

export function Tabs({ tabs, activeTab, onTabChange }: TabsProps) {
  return (
    <nav className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          className={`tab${tab.id === activeTab ? " active" : ""}`}
          role="tab"
          aria-selected={tab.id === activeTab}
          onClick={() => onTabChange(tab.id)}
        >
          {tab.label}
          {tab.badge != null && (
            <span className={`tab-badge nav-item-badge ${tab.badgeTone ?? ""}`}>
              {tab.badge}
            </span>
          )}
        </button>
      ))}
    </nav>
  );
}
