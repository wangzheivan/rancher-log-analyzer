import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

test("问题发现：快照、历史信号、未知、事件与原文", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const c = await (
    await request.post("/api/v1/cases", {
      data: { name: "Analysis browser regression" },
    })
  ).json();
  try {
    const b = await (
      await request.post(
        `/api/v1/cases/${c.id}/bundles?filename=analysis.tar.gz`,
        { data: readFileSync("/tmp/rancher-analysis-fixture.tar.gz") },
      )
    ).json();
    const base = `/api/v1/bundles/${b.id}`;
    await expect
      .poll(async () => (await (await request.get(base)).json()).state)
      .toBe("ready");
    await expect
      .poll(
        async () =>
          (await (await request.get(base + "/analysis")).json()).state,
      )
      .toBe("complete");
    const goto = async (values: Record<string, string> = {}) =>
      page.goto(
        "/#" +
          new URLSearchParams({
            case: c.id,
            bundle: b.id,
            page: "analysis",
            ...values,
          }),
      );
    await goto();
    await expect(
      page.getByRole("heading", { name: "问题发现", exact: true }),
    ).toBeVisible();
    await expect(page.locator(".analysis-observations").last()).toContainText(
      "CPU非空闲",
    );
    await page.getByLabel("发现类别").selectOption("cluster");
    await page.getByLabel("搜索发现").fill("app-failed");
    await expect(page.locator(".finding-card")).toHaveCount(1);
    await expect(page.locator(".finding-card")).toContainText(
      "synthetic registry denied image",
    );
    await page
      .getByRole("button", { name: "查看证据与关联事件", exact: true })
      .click();
    await expect(page.locator(".finding-detail")).toContainText("UID");
    await page
      .locator(".finding-detail")
      .getByRole("button", { name: "查看原文", exact: true })
      .first()
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("button", { name: "关闭文件" }).click();
    await page.getByRole("button", { name: "查看对象 →" }).first().click();
    await expect(
      page.getByRole("heading", { name: "Pod 详情", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "← 返回并恢复列表" }).click();
    await expect(page.getByLabel("搜索发现")).toHaveValue("app-failed");
    await page.getByRole("tab", { name: "日志中的历史信号" }).click();
    await page.getByLabel("发现类别").selectOption("etcd");
    await page.getByLabel("搜索发现").fill("");
    await expect(page.locator(".finding-card")).toHaveCount(1);
    await expect(page.locator(".finding-card")).toContainText("历史命中 15 次");
    await page
      .getByRole("button", { name: "查看证据与关联事件", exact: true })
      .click();
    await expect(page.locator(".evidence-list > div")).toHaveCount(10);
    await page
      .locator(".finding-detail .pager")
      .first()
      .getByRole("button", { name: "下一页" })
      .click();
    await expect(page.locator(".evidence-list > div")).toHaveCount(5);
    await page.getByRole("tab", { name: "未能完成的检查" }).click();
    await page.getByLabel("发现类别").selectOption("initialization");
    await expect(page.locator(".finding-list")).toContainText("cgroup");
    await page.getByRole("button", { name: "重新分析", exact: true }).click();
    await expect
      .poll(
        async () =>
          (await (await request.get(base + "/analysis")).json()).state,
      )
      .toBe("complete");
    for (const width of [1440, 1280, 1024, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await goto();
      await expect(page.locator(".finding-card").first()).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        "analysis @" + width,
      ).toBe(true);
    }
    await page.screenshot({
      path: "../artifacts/analysis-synthetic.png",
      fullPage: true,
    });
    expect(errors).toEqual([]);
  } finally {
    await request.delete(`/api/v1/cases/${c.id}`);
  }
});

test("真实包初筛：异常Pod、服务角色与etcd证据", async ({ page, request }) => {
  test.skip(!process.env.DISPLAY_ARCHIVE, "Explicit private fixture only");
  const c = await (
    await request.post("/api/v1/cases", {
      data: { name: "Private analysis acceptance" },
    })
  ).json();
  try {
    const b = await (
      await request.post(`/api/v1/cases/${c.id}/bundles?filename=real.tar.gz`, {
        data: readFileSync(process.env.DISPLAY_ARCHIVE!),
      })
    ).json();
    const base = `/api/v1/bundles/${b.id}`;
    await expect
      .poll(async () => (await (await request.get(base)).json()).state, {
        timeout: 60000,
      })
      .toBe("ready");
    await expect
      .poll(
        async () =>
          (await (await request.get(base + "/analysis")).json()).state,
        { timeout: 60000 },
      )
      .toMatch(/complete|partial/);
    let status = await (await request.get(base + "/analysis")).json();
    for (let i = 0; i < 5 && status.state === "partial"; i++) {
      await request.post(base + "/analysis", { data: { action: "continue" } });
      await expect
        .poll(
          async () =>
            (await (await request.get(base + "/analysis")).json()).state,
          { timeout: 60000 },
        )
        .toMatch(/complete|partial/);
      status = await (await request.get(base + "/analysis")).json();
    }
    expect(status.state).toBe("complete");
    expect(status.coverage.remainingBytes).toBe(0);
    const list = await (
      await request.get(
        base + "/analysis/findings?limit=200&evidence_type=snapshot",
      )
    ).json();
    expect(
      list.items.filter(
        (r: any) =>
          r.ruleId === "pod.state" && r.observed.includes("ImagePullBackOff"),
      ).length,
    ).toBe(9);
    expect(
      list.items.some((r: any) => r.ruleId === "service.distribution"),
    ).toBe(false);
    expect(list.items.some((r: any) => r.ruleId === "etcd.leader")).toBe(false);
    expect(list.items.some((r: any) => r.ruleId === "init.swap")).toBe(false);
    await page.goto(
      "/#" +
        new URLSearchParams({
          case: c.id,
          bundle: b.id,
          page: "analysis",
          q: "ImagePullBackOff",
        }),
    );
    await expect(page.locator(".finding-card")).toHaveCount(9);
    await expect(page.locator(".finding-card").first()).toContainText(
      "名称关联",
    );
    await page.screenshot({
      path: "../artifacts/analysis-private.png",
      fullPage: true,
    });
  } finally {
    await request.delete(`/api/v1/cases/${c.id}`);
  }
});
