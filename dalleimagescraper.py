from queue import Empty
from tokenize import String
from waybackpy import WaybackMachineSaveAPI, WaybackMachineCDXServerAPI
import requests
from bs4 import BeautifulSoup
from collections import namedtuple
from itertools import islice
import shelve
import time, datetime
import argparse

# all of the published images are posted here, one image per page (e.g. https://labs.openai.com/s/00J93OMgvNdWQNY4bPVg5qIl)
# TODO: not sure if this includes from other sources besides Dall-E 2 ; might revisit this later for more fine-grained indexing
url = "https://labs.openai.com/s/*"
user_agent = "Mozilla/5.1 (Windows NT 5.1; rv:40.0) Gecko/20100101 Firefox/40.0"

# single image record
Record = namedtuple('Record', ['url', 'imageurl', 'description', 'datecreated', 'valid'])
CacheRange = namedtuple('CacheRange', ['start', 'end'])

def get_image_meta(url):
    # reach out to image page (e.g. https://labs.openai.com/s/00J93OMgvNdWQNY4bPVg5qIl) and scrape metadata
    page = requests.get(url)
    soup = BeautifulSoup(page.content, "html.parser")
    
    prompt = soup.find('meta', property="og:title")["content"]
    prompt =  prompt.partition("|")[-1].strip() # strip off everything to left of the first "|" which is a generic Dall-E label
    imglink = soup.find('meta', property="og:image")["content"]
    
    return [prompt, imglink]


# cache so we're not pulling stuff we know about every time we run the script
def load_cache(filename):
    with shelve.open(filename) as db:
        return [
            db.get("records", dict()), 
            db.get("cacherange", CacheRange(None, None))
            ]

def save_cache(records, cacherange, filename):
    with shelve.open(filename) as db:
        db["records"]       = records
        db["cacherange"]    = cacherange

def update_cache(records, cacherange, since):

    # if wanting items starting in a period we have cached, just immmediately skip to the end of the existing cache to start retrieving more
    if cacherange.start and cacherange.end and since > cacherange.start <= since <= cacherange.end:
        since = cacherange.end

    # use WaybckMachine to discover archived images posted on OpenAI since the last time we checked
    cdx = WaybackMachineCDXServerAPI(url, user_agent, start_timestamp=since.strftime("%Y%m%d%H%M%S"), end_timestamp=datetime.datetime.now().year+1)

    # iterate through archived pages, and if it's the first time seeing it then visit the page to get the prompt
    for item in sorted(list(cdx.snapshots()), key=lambda item: item.datetime_timestamp):
        if item.original in records: # dup record, already processed (Wayback has multiple snapshots of same page or we may have already processed this query date range)
            continue
        print(f'retreiving metadata for: {item.datetime_timestamp} - {item.original}')
        prompt, imglink = get_image_meta(item.original)
        # error page for OpenAI image has same metadata, so only good way to tell if it's an error is if there's no prompt
        # assign record, setting it to not valid if there is no prompt (some images have been deleted)
        records[item.original] = Record(item.original, imglink, prompt, item.datetime_timestamp, bool(prompt))

        # update the known cache range
        if cacherange.end and item.datetime_timestamp > cacherange.end:
            cacherange = CacheRange(cacherange.start, max (item.datetime_timestamp, cacherange.end))
    save_cache(records, cacherange, "records")  

def generatemarkdownfile(records, filename, since = datetime.datetime(2000,1,1), title = "Dall-E 2 Images"):
    # generate a markdown file from records

    # output in sorted order
    dayforheader = -1   
    lines = []
    lines.append(f"# {title}")
    count = 0

    firstday = Empty

    for v in sorted(list(records.items()), key=lambda item: item[1].datecreated, reverse=True):
        if (not v[1].valid):
            continue
        # TODO: this list should be prefiltered so we don't have to iterate over older records
        if (v[1].datecreated < since):
            continue

        if v[1].datecreated.day != dayforheader:
            dayforheader = v[1].datecreated.day
            lines.append(f"### {v[1].datecreated.date()}")
            if firstday == Empty:
                firstday = dayforheader

        # ugly hack to get rid of embedded markup symbols; need to regex or better get a library for this cleanup
        # probably doesn't cover all cases
        prompt = v[1].description.replace("\n"," ! ").replace("#",".").replace(">",".").replace("-","!")
        img = ""

        # generate thumbnails for first day (again, ugly hack)
        if firstday == v[1].datecreated.day:
            img = "[<img src=\"{}\" width=\"200\"/>]({})".format(v[1].imageurl, v[1].imageurl)
 
        lines.append (f"* {img} [{prompt}]({v[1].url})")
        
    with open(filename,"w",encoding="utf-8") as f:
        f.write("\n".join(lines))

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--since", type=datetime.datetime.fromisoformat, default="2020-01-01", help="Generate a markdown for records since this date. Date format: YYYY-MM-DD")
    parser.add_argument("-f", "--filename", default="dallelinks.md", help="Output file for markup.")
    args = parser.parse_args()

    # load records from cache and update
    records, cacherange = load_cache("records")

    update_cache(records, cacherange, args.since)
    
    generatemarkdownfile(records, args.filename, args.since)
    
    print (f"Markdown saved in {args.filename}")

if __name__  == "__main__":
    main()