/**
 * Protected external acceptance contract for Excalidraw find and replace.
 * Run through the check-owned TMPDIR wrapper, never install in the candidate.
 * All changes below are driven through the rendered application controls.
 */
import React from "react";
import { vi } from "vitest";

import { BOUND_TEXT_PADDING, CLASSES, KEYS } from "@excalidraw/common";
import { CaptureUpdateAction } from "@excalidraw/element";
import type { ExcalidrawElement } from "@excalidraw/element/types";
import { Excalidraw } from "@excalidraw/excalidraw";
import { createRedoAction, createUndoAction } from "@excalidraw/excalidraw/actions/actionHistory";
import { API } from "@excalidraw/excalidraw/tests/helpers/api";
import { Keyboard } from "@excalidraw/excalidraw/tests/helpers/ui";
import {
  act,
  fireEvent,
  render,
  screen,
  unmountComponent,
  waitFor,
} from "@excalidraw/excalidraw/tests/test-utils";

const { h } = window;
const TIMEOUT = 2500;
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const byId = (id: string) => h.elements.find((element) => element.id === id)!;
const textById = (id: string) => byId(id) as Extract<ExcalidrawElement, { type: "text" }>;
const frameById = (id: string) => byId(id) as Extract<ExcalidrawElement, { type: "frame" }>;
const matches = () => h.state.searchMatches?.matches ?? [];

const text = (id: string, value: string, y = 0) =>
  API.createElement({ type: "text", id, text: value, x: 100, y });

const seed = async (elements: ExcalidrawElement[]) => {
  API.updateScene({ elements, captureUpdate: CaptureUpdateAction.IMMEDIATELY });
  await waitFor(() => expect(h.elements.length).toBe(elements.length));
};

const searchInput = () => {
  const input = h.app.excalidrawContainerValue.container?.querySelector<HTMLInputElement>(
    `.${CLASSES.SEARCH_MENU_INPUT_WRAPPER} input`,
  );
  expect(input).not.toBeNull();
  return input!;
};

const setValue = (input: HTMLInputElement | HTMLTextAreaElement, value: string) => {
  fireEvent.change(input, { target: { value } });
};

const openQuery = async (query: string, expectedMatches: number) => {
  Keyboard.withModifierKeys({ ctrl: true }, () => Keyboard.keyPress(KEYS.F));
  await waitFor(() => expect(searchInput().matches(":focus")).toBe(true));
  // Upstream's search debounce and focused-match index are module-level, so a
  // search from a previous editor instance can leave the index set. An empty
  // query resets it through the real input before the measured query.
  setValue(searchInput(), "");
  await new Promise((resolve) => setTimeout(resolve, 450));
  setValue(searchInput(), query);
  // Upstream focuses the first match asynchronously after counting matches.
  await waitFor(() => {
    expect(matches()).toHaveLength(expectedMatches);
    if (expectedMatches) expect(matches().filter((match) => match.focus)).toHaveLength(1);
  }, { timeout: TIMEOUT });
};

const replacementInput = async () => {
  let input: HTMLInputElement | HTMLTextAreaElement;
  await waitFor(() => {
    input = screen.getByRole("textbox", { name: /^replace with$/i }) as
      | HTMLInputElement
      | HTMLTextAreaElement;
  }, { timeout: TIMEOUT });
  return input!;
};

const replaceButton = (all = false) => screen.getByRole("button", {
  name: all ? /^replace all$/i : /^replace$/i,
});

const replaceWith = async (value: string, all = false) => {
  setValue(await replacementInput(), value);
  fireEvent.click(replaceButton(all));
};

// Content/geometry identity excludes audit counters which legitimately change
// on undo/redo. This compares the complete user-visible scene, not a new helper.
const sceneContent = () => h.elements.map((element) => {
  const {
    version,
    versionNonce,
    updated,
    ...content
  } = copy(element);
  return content;
});

describe("protected Parallax find-and-replace acceptance", () => {
  beforeEach(async () => {
    unmountComponent();
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    await render(<Excalidraw handleKeyboardGlobally />);
    // jsdom measures every element as 0x0, and upstream search focuses only
    // visible matches. Give the editor a stable desktop-sized viewport so each
    // re-measure agrees, then apply it.
    const container = h.app.excalidrawContainerValue.container!;
    vi.spyOn(container, "getBoundingClientRect").mockReturnValue(
      { x: 0, y: 0, left: 0, top: 0, right: 1280, bottom: 800, width: 1280, height: 800, toJSON: () => ({}) } as DOMRect,
    );
    API.setAppState({ openSidebar: null, width: 1280, height: 800 });
  });

  it("preserves ordinary literal, case-insensitive search and Enter cycling without edits", async () => {
    await seed([text("plain-a", "Target target", 0), text("plain-b", "TARGET", 150)]);
    const before = copy(h.elements);
    await openQuery("target", 3);
    expect(matches().filter((match) => match.focus)).toHaveLength(1);
    const focused = matches().findIndex((match) => match.focus);
    Keyboard.keyPress(KEYS.ENTER, searchInput());
    expect(matches().findIndex((match) => match.focus)).toBe((focused + 1) % 3);
    expect(h.elements).toEqual(before);

    setValue(searchInput(), "[.*]");
    await waitFor(() => expect(matches()).toHaveLength(0), { timeout: TIMEOUT });
    expect(h.elements).toEqual(before);
  });

  it("replaces only the selected occurrence and refreshes result count", async () => {
    await seed([text("one", "target target target", 0), text("other", "target", 150)]);
    await openQuery("target", 4);
    Keyboard.keyPress(KEYS.ENTER, searchInput());
    expect(matches().findIndex((match) => match.focus)).toBe(1);
    await replaceWith("done");
    await waitFor(() => expect(textById("one").originalText).toBe("target done target"));
    expect(textById("other").originalText).toBe("target");
    await waitFor(() => expect(matches()).toHaveLength(3), { timeout: TIMEOUT });
    expect(textById("one").text).toBe("target done target");
  });

  it("replaces all mixed-case occurrences in text and explicit frame names", async () => {
    const frame = API.createElement({ type: "frame", id: "named-frame", x: 0, y: 0, width: 600, height: 400 });
    API.updateElement(frame, { name: "Target target board" });
    const lockedFrame = API.createElement({ type: "frame", id: "locked-frame", x: 0, y: 600, locked: true });
    API.updateElement(lockedFrame, { name: "target locked board" });
    await seed([frame, lockedFrame, text("all-a", "TARGET then target", 30), text("all-b", "target", 120)]);
    const lockedBefore = copy(byId("locked-frame"));
    await openQuery("target", 6);
    await replaceWith("new", true);
    await waitFor(() => expect(frameById("named-frame").name).toBe("new new board"));
    expect(textById("all-a").originalText).toBe("new then new");
    expect(textById("all-b").originalText).toBe("new");
    expect(byId("locked-frame")).toEqual(lockedBefore);
    await waitFor(() => expect(matches()).toHaveLength(1), { timeout: TIMEOUT });
  });

  it("keeps implicit default frame names searchable without materializing or replacing them", async () => {
    const frame = API.createElement({ type: "frame", id: "implicit-frame", x: 0, y: 0 });
    await seed([frame]);
    expect(frameById("implicit-frame").name).toBeNull();
    await openQuery("frame", 1);
    const before = copy(h.elements);
    setValue(await replacementInput(), "Board");
    expect(replaceButton()).toBeDisabled();
    expect(replaceButton(true)).toBeDisabled();
    fireEvent.click(replaceButton(true));
    expect(h.elements).toEqual(before);
  });

  it("treats regexp query metacharacters and JavaScript replacement tokens literally", async () => {
    const query = "[a].*+$?^(){}|\\";
    const replacement = "$&-$1-$$-\\-🧭";
    await seed([text("literal", `before ${query} between ${query} after`), text("unrelated", "aaab should not match", 100)]);
    await openQuery(query, 2);
    await replaceWith(replacement, true);
    await waitFor(() => expect(textById("literal").originalText).toBe(`before ${replacement} between ${replacement} after`));
    expect(textById("unrelated").originalText).toBe("aaab should not match");
  });

  it("handles Unicode and multiline replacement without corrupting neighboring text", async () => {
    await seed([text("unicode", "first 猫🐈 café\nsecond 猫🐈 τέλος")]);
    await openQuery("猫🐈", 2);
    await replaceWith("犬🐕\n続き", true);
    await waitFor(() => expect(textById("unicode").originalText).toBe("first 犬🐕\n続き café\nsecond 犬🐕\n続き τέλος"));
    expect(textById("unicode").text).toBe(textById("unicode").originalText);
    expect(textById("unicode").height).toBeGreaterThan(0);
    expect(Number.isFinite(textById("unicode").width)).toBe(true);
  });

  it("supports deleting matches with an explicitly empty replacement", async () => {
    await seed([text("delete", "keep target tail target")]);
    await openQuery("target", 2);
    await replaceWith("", true);
    await waitFor(() => expect(textById("delete").originalText).toBe("keep  tail "));
    await waitFor(() => expect(matches()).toHaveLength(0), { timeout: TIMEOUT });
  });

  it("does not repeatedly replace generated matches when replacement contains the query", async () => {
    await seed([text("finite", "target target")]);
    await openQuery("target", 2);
    await replaceWith("target!", true);
    await waitFor(() => expect(textById("finite").originalText).toBe("target! target!"));
    await waitFor(() => expect(matches()).toHaveLength(2), { timeout: TIMEOUT });
    expect(textById("finite").originalText).toBe("target! target!");
  });

  it("protects both locked text and text bound to a locked container", async () => {
    const lockedText = text("locked-text", "target", 0);
    API.updateElement(lockedText, { locked: true });
    const container = API.createElement({ type: "rectangle", id: "locked-box", x: 50, y: 120, locked: true });
    const label = API.createElement({ type: "text", id: "locked-label", text: "target", containerId: container.id, x: 70, y: 140 });
    API.updateElement(container, { boundElements: [{ type: "text", id: label.id }] });
    await seed([lockedText, container, label, text("editable", "target", 300)]);
    const protectedBefore = copy(h.elements.filter((element) => element.id !== "editable"));
    await openQuery("target", 3);
    await replaceWith("changed", true);
    await waitFor(() => expect(textById("editable").originalText).toBe("changed"));
    expect(h.elements.filter((element) => element.id !== "editable")).toEqual(protectedBefore);
    await waitFor(() => expect(matches()).toHaveLength(2), { timeout: TIMEOUT });
    expect(replaceButton(true)).toBeDisabled();
  });

  it("reflows bound text inside its container while preserving identity, bindings and unrelated elements", async () => {
    const box = API.createElement({ type: "rectangle", id: "geometry-box", x: 100, y: 100, width: 180, height: 70 });
    const label = API.createElement({ type: "text", id: "geometry-label", text: "target", containerId: box.id, textAlign: "center", verticalAlign: "middle", x: 150, y: 120 });
    API.updateElement(box, { boundElements: [{ type: "text", id: label.id }] });
    const untouched = API.createElement({ type: "ellipse", id: "untouched", x: 500, y: 300 });
    await seed([box, label, untouched]);
    const untouchedBefore = copy(byId(untouched.id));
    await openQuery("target", 1);
    const replacement = "A long first line with several words\nA long second line with several words\nA third line";
    await replaceWith(replacement, true);
    await waitFor(() => expect(textById(label.id).originalText).toBe(replacement));
    const nextLabel = textById(label.id);
    const nextBox = byId(box.id);
    expect(nextLabel.containerId).toBe(box.id);
    expect(nextBox.boundElements).toEqual([{ type: "text", id: label.id }]);
    expect(nextBox.x).toBe(100);
    expect(nextBox.y).toBe(100);
    expect(nextBox.height).toBeGreaterThan(70);
    expect(nextLabel.height).toBeGreaterThan(20);
    expect(nextLabel.width).toBeGreaterThan(0);
    expect(nextLabel.width).toBeLessThanOrEqual(nextBox.width - BOUND_TEXT_PADDING * 2 + 0.01);
    expect(nextLabel.height).toBeLessThanOrEqual(nextBox.height - BOUND_TEXT_PADDING * 2 + 0.01);
    expect(nextLabel.x + nextLabel.width / 2).toBeCloseTo(nextBox.x + nextBox.width / 2, 4);
    expect(nextLabel.y + nextLabel.height / 2).toBeCloseTo(nextBox.y + nextBox.height / 2, 4);
    for (const value of [nextLabel.x, nextLabel.y, nextLabel.width, nextLabel.height, nextBox.width, nextBox.height]) {
      expect(Number.isFinite(value)).toBe(true);
    }
    expect(byId(untouched.id)).toEqual(untouchedBefore);
  });

  it("preserves arrow label bindings and valid text geometry", async () => {
    const arrow = API.createElement({ type: "arrow", id: "label-arrow", x: 100, y: 100, width: 200, height: 0 });
    const label = API.createElement({ type: "text", id: "arrow-label", text: "target", containerId: arrow.id, x: 170, y: 90 });
    API.updateElement(arrow, { boundElements: [{ type: "text", id: label.id }] });
    await seed([arrow, label]);
    const originalPoints = copy((byId(arrow.id) as Extract<ExcalidrawElement, { type: "arrow" }>).points);
    await openQuery("target", 1);
    await replaceWith("new label", true);
    await waitFor(() => expect(textById(label.id).originalText).toBe("new label"));
    expect(textById(label.id).containerId).toBe(arrow.id);
    expect(byId(arrow.id).boundElements).toEqual([{ type: "text", id: label.id }]);
    expect((byId(arrow.id) as Extract<ExcalidrawElement, { type: "arrow" }>).points).toEqual(originalPoints);
    expect(textById(label.id).height).toBeGreaterThan(0);
    expect(textById(label.id).width).toBeGreaterThan(0);
    expect(Number.isFinite(textById(label.id).x)).toBe(true);
    expect(Number.isFinite(textById(label.id).y)).toBe(true);
  });

  it("commits Replace all as exactly one undoable edit including geometry and frame names", async () => {
    const box = API.createElement({ type: "rectangle", id: "undo-box", x: 100, y: 100, width: 150, height: 70 });
    const label = API.createElement({ type: "text", id: "undo-label", text: "target", containerId: box.id, x: 120, y: 120 });
    API.updateElement(box, { boundElements: [{ type: "text", id: label.id }] });
    const frame = API.createElement({ type: "frame", id: "undo-frame", x: 0, y: 0, width: 650, height: 450 });
    API.updateElement(frame, { name: "target board" });
    await seed([frame, box, label, text("undo-other", "target target", 300)]);
    await openQuery("target", 4);
    setValue(await replacementInput(), "replacement line\nsecond line\nthird line");
    const before = sceneContent();
    const undoCount = API.getUndoStack().length;
    fireEvent.click(replaceButton(true));
    await waitFor(() => expect(textById("undo-label").originalText).toBe("replacement line\nsecond line\nthird line"));
    expect(API.getUndoStack()).toHaveLength(undoCount + 1);
    const after = sceneContent();
    expect(after).not.toEqual(before);
    API.executeAction(createUndoAction(h.history));
    await waitFor(() => expect(sceneContent()).toEqual(before));
    API.executeAction(createRedoAction(h.history));
    await waitFor(() => expect(sceneContent()).toEqual(after));
  });

  it("never applies an old query after a rapid query change", async () => {
    await seed([text("old-query", "alpha alpha", 0), text("new-query", "beta beta", 150)]);
    await openQuery("alpha", 2);
    setValue(await replacementInput(), "done");
    const all = replaceButton(true);
    setValue(searchInput(), "beta");
    fireEvent.click(all);
    expect(textById("old-query").originalText).toBe("alpha alpha");
    // Safe implementations may recompute synchronously, or disable until the
    // new query is ready. Both are allowed; editing alpha is never allowed.
    if (textById("new-query").originalText === "beta beta") {
      await waitFor(() => expect(matches().every((match) => match.id === "new-query") && matches().length === 2).toBe(true), { timeout: TIMEOUT });
      fireEvent.click(replaceButton(true));
    }
    await waitFor(() => expect(textById("new-query").originalText).toBe("done done"));
    expect(textById("old-query").originalText).toBe("alpha alpha");
  });

  it("uses current scene text and current container lock state instead of stale match objects", async () => {
    const box = API.createElement({ type: "rectangle", id: "late-lock-box", x: 100, y: 150 });
    const label = API.createElement({ type: "text", id: "late-lock-label", text: "needle", containerId: box.id, x: 120, y: 170 });
    API.updateElement(box, { boundElements: [{ type: "text", id: label.id }] });
    await seed([text("scene-current", "needle tail", 0), box, label]);
    await openQuery("needle", 2);
    setValue(await replacementInput(), "done");
    API.updateElement(textById("scene-current"), { text: "prefix needle suffix", originalText: "prefix needle suffix" });
    API.updateElement(byId(box.id), { locked: true });
    const protectedBefore = copy([byId(box.id), byId(label.id)]);
    fireEvent.click(replaceButton(true));
    expect([byId(box.id), byId(label.id)]).toEqual(protectedBefore);
    if (textById("scene-current").originalText === "prefix needle suffix") {
      await waitFor(() => expect(replaceButton(true)).not.toBeDisabled(), { timeout: TIMEOUT });
      fireEvent.click(replaceButton(true));
    }
    await waitFor(() => expect(textById("scene-current").originalText).toBe("prefix done suffix"));
    expect([byId(box.id), byId(label.id)]).toEqual(protectedBefore);
  });

  it("blocks replacement for empty/no-match queries and leaves history unchanged", async () => {
    await seed([text("no-op", "keep this")]);
    await openQuery("missing", 0);
    setValue(await replacementInput(), "changed");
    const before = copy(h.elements);
    const undoCount = API.getUndoStack().length;
    expect(replaceButton()).toBeDisabled();
    expect(replaceButton(true)).toBeDisabled();
    fireEvent.click(replaceButton(true));
    setValue(searchInput(), "   ");
    await waitFor(() => expect(matches()).toHaveLength(0), { timeout: TIMEOUT });
    expect(replaceButton(true)).toBeDisabled();
    fireEvent.click(replaceButton(true));
    expect(h.elements).toEqual(before);
    expect(API.getUndoStack()).toHaveLength(undoCount);
  });

  it("keeps search available in view mode while refusing all replacement mutations", async () => {
    await seed([text("read-only", "target target")]);
    await openQuery("target", 2);
    setValue(await replacementInput(), "changed");
    API.setAppState({ viewModeEnabled: true });
    const before = copy(h.elements);
    const undoCount = API.getUndoStack().length;
    // Hiding edit controls and disabling them are both valid read-only UI.
    for (const name of [/^replace$/i, /^replace all$/i]) {
      const button = screen.queryByRole("button", { name });
      if (button) {
        expect(button).toBeDisabled();
        fireEvent.click(button);
      }
    }
    Keyboard.keyPress(KEYS.ENTER, searchInput());
    expect(matches()).toHaveLength(2);
    expect(h.elements).toEqual(before);
    expect(API.getUndoStack()).toHaveLength(undoCount);
  });
});
