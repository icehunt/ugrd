__author__ = "desultory"
__version__ = "0.1.0"

from zenlib.util import contains


@contains("squashfs_image", "squashfs_image must be set to the path of the squashfs image to mount.", raise_exception=True)
def mount_squashfs(self):
    """
    Returns bash lines to mount squashfs image.
    Creates /run/squashfs directory to mount squashfs image.
    Creates /run/upperdir and /run/workdir directories for overlayfs.
    """
    return ["mkdir -p /run/squashfs",
            f"mount -t squashfs -o loop {self.squashfs_image} /run/squashfs || rd_fail 'Failed to mount squashfs image: {self.squashfs_image}'",
            "mkdir -p /run/upperdir",
            "mkdir -p /run/workdir",
            f"mount -t overlay overlay -o lowerdir=/run/squashfs,upperdir=/run/upperdir,workdir=/run/workdir {self.mounts['root']['destination']} || rd_fail 'Failed to mount overlayfs'"]