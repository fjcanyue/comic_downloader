# Basic Usage

This guide will walk you through the basic usage of the Comic Downloader.

## 1. Launch the tool

Open your terminal and run the following command:

```bash
main
```

You will be greeted with a welcome message and a prompt.

## 2. Select a source

Before you can start downloading comics, you need to select a source. The tool supports multiple comic sources.

To see the available sources, type `source` and press Enter. A list of supported sources will be displayed.

Enter the number corresponding to the source you want to use.

## 3. Search for a comic

Once you have selected a source, you can search for comics.

Use the `s` command followed by your search query. For example:

```bash
s one piece
```

The tool will display a list of search results with their corresponding index numbers.

## 4. View comic details

To view more details about a comic, use the `i` command followed by the index number from the search results.

```bash
i 0
```

This will display information about the comic, including its chapters.

## 5. Download comics

There are two ways to download comics:

### Download all chapters

To download all chapters of a comic, use the `d` command followed by the index number from the search results.

```bash
d 0
```

### Download a range of chapters

To download a specific range of chapters, use the `v` command. You need to view the comic details first to see the chapter list.

The `v` command has three modes:

-   `v <chapter_index>`: Download all episodes in a specific chapter.
-   `v <chapter_index> <to_episode_index>`: Download episodes from the beginning of the chapter up to a specific episode.
-   `v <chapter_index> <from_episode_index> <to_episode_index>`: Download a specific range of episodes within a chapter.

For example:

```bash
v 0 5 10
```

This will download episodes 5 to 10 from the first chapter.

## 6. Quit the application

To exit the tool, type `q` and press Enter.
