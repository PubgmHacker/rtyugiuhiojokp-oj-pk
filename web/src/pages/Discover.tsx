import { useEffect } from "react";
import SwipeDeck from "../components/SwipeDeck";
import { useStore } from "../lib/store";

export default function Discover() {
  const { user } = useStore();

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 safe-top">
        <h1 className="text-2xl font-bold bg-gradient-to-r from-accent to-warn bg-clip-text text-transparent">
          Souldawn
        </h1>
        <div className="flex items-center gap-2">
          {user?.is_verified && (
            <span className="text-xs px-2 py-1 bg-success/20 text-success rounded-full">✓ Верифицирован</span>
          )}
        </div>
      </header>

      <SwipeDeck />
    </div>
  );
}
