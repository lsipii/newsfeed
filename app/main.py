import math
from typing import TypedDict
from dotenv import load_dotenv
import sys

from app.NewsFeed import NewsFeed
from config import news_sources
from ursina import Ursina, color as ursina_color, held_keys, Text, Entity
import webbrowser


class LinkText(Text):
    """An interactive text entity that opens a URL when clicked."""

    def __init__(self, text, url, **kwargs):
        super().__init__(text=text, color=ursina_color.black, **kwargs)
        self.url = url
        self.original_color = ursina_color.black
        self.collider = "box"  # Add a collider for mouse interaction

    def on_mouse_enter(self):
        """Highlight the link on hover."""
        if not self.url:
            return
        # print("Link hovered")
        self.color = ursina_color.lime

    def on_mouse_exit(self):
        """Reset the color when not hovered."""
        if not self.url:
            return
        self.color = self.original_color

    def on_click(self):
        """Open the link in the default browser."""
        if not self.url:
            return
        webbrowser.open(self.url)
        print(f"Opened {self.url}")


class PaneContent(TypedDict):
    text: str
    url: str


class Pane(Entity):
    """A class representing a 3D pane."""

    def __init__(
        self,
        position=(0, 0, 0),
        scale=(1, 1),
        color=ursina_color.azure,
        title="",
        contents: list[PaneContent] = [],
        **kwargs,
    ):
        super().__init__(
            model="quad",  # 2D
            position=position,
            scale=scale,
            color=color,
            collider="box",  # Collider
            **kwargs,
        )
        self.original_color = color
        self.original_z = self.z

        y_position = 0.4
        contents.insert(0, {"text": title, "url": ""})
        for content in contents:
            LinkText(
                text=content["text"],
                url=content["url"],
                parent=self,
                position=(-0.4, y_position, self.z - 0.2),
                scale=(self.scale.x / 2.4, self.scale.y / 2.4),
                wordwrap=40,
            )
            y_position -= 0.15

    def on_mouse_enter(self):
        self.color = ursina_color.lime  # Highlight pane when hovered
        self.z -= 0.1  # Move the pane forward

    def on_mouse_exit(self):
        self.color = self.original_color  # Reset color when not hovered
        self.z = self.original_z  # Reset z position


class MyApp:
    def __init__(self):
        self.app = Ursina(development_mode=True)

        load_dotenv()
        self.news_feed = NewsFeed(
            news_sources=news_sources,
        )

        self.panes = []
        self.selected_pane = None
        self.create_panes()

        # Assign input handling to the class method
        self.app.input = self.input

    def create_panes(self):
        """Create some example panes."""
        articles = self.news_feed.get_latest_articles()
        articles_grouped_by_source = {}
        for article in articles:
            source = article["source"]["name"]
            if source not in articles_grouped_by_source:
                articles_grouped_by_source[source] = []
            articles_grouped_by_source[source].append(
                {
                    "text": f"{article['publishedAt']} - {article['title']}",
                    "url": article["url"],
                }
            )

        # Parameters for the ellipse
        a = 2.5  # Semi-major axis
        b = 3  # Semi-minor axis
        rotation_angle = math.radians(30)  # Ellipse rotation angle in radians
        total_sources = len(articles_grouped_by_source)

        # Find the range of scaling factors
        positioned_sources = []
        for index, (source, articles) in enumerate(articles_grouped_by_source.items()):
            # pick latest 5 articles
            latest_articles = articles[:5]

            # Calculate the position of the pane on the ellipse
            theta = 2 * math.pi * index / total_sources  # Angle around the ellipse
            x = a * math.cos(theta)
            y = b * math.sin(theta)
            x_rotated = x * math.cos(rotation_angle) - y * math.sin(rotation_angle)
            y_rotated = x * math.sin(rotation_angle) + y * math.cos(rotation_angle)

            positioned_sources.append((x_rotated, y_rotated, source, latest_articles))

        # Calculate scaling factors based on x+y values
        min_sum = min(x + y for x, y, s, a in positioned_sources)
        max_sum = max(x + y for x, y, s, a in positioned_sources)

        for x, y, source, latest_articles in positioned_sources:
            scale_factor = 1 - (
                (x + y - min_sum) / (max_sum - min_sum)
            )  # Scale from 1 (largest) to near 0 (smallest)

            adjust_factor = 1.5 if scale_factor >= 0.5 else 1.6
            adjusted_scale_factor = adjust_factor + adjust_factor * scale_factor
            self.panes.append(
                Pane(
                    position=(x, y, 0),
                    scale=(
                        adjusted_scale_factor,
                        adjusted_scale_factor,
                        adjusted_scale_factor,
                    ),
                    color=ursina_color.random_color(),
                    title=source,
                    contents=latest_articles,
                )
            )

    def input(self, key):
        """Handle user input."""

        # Catch quit calls
        if key == "escape up" or (
            "left control" in held_keys
            and held_keys["left control"] == 1
            and key == "c up"
        ):
            self.exit()

        if key == "mouse1 up":
            self.selected_pane = None  # Deselect the pane

            # Select the hovered pane
            for pane in self.panes:
                if pane.hovered:
                    self.selected_pane = pane
                    break

        if self.selected_pane:
            trimmed_key = key.replace(" up", "")
            match trimmed_key:
                case "arrow_up" | "w":
                    self.selected_pane.z += 0.1  # Move forward
                case "down arrow" | "s":
                    self.selected_pane.z -= 0.1  # Move backward
                case "left arrow" | "a":
                    if "left shift" in held_keys and held_keys["left shift"] == 1:
                        self.selected_pane.scale_x += 0.1  # Expand horizontally
                    else:
                        self.selected_pane.scale_x -= 0.1  # Shrink horizontally
                case "right arrow" | "d":
                    if "left shift" in held_keys and held_keys["left shift"] == 1:
                        self.selected_pane.scale_y += 0.1  # Expand horizontally
                    else:
                        self.selected_pane.scale_y -= 0.1  # Shrink horizontally

    def update(self):
        """Optional: Add frame updates if needed."""
        pass

    def run(self):
        """Run the app."""
        self.app.run()

    def exit(self):
        sys.exit(0)


def main():
    # newsfeed()
    app = MyApp()
    app.run()


if __name__ == "__main__":
    main()
